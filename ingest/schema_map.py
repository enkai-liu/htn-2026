"""Schema matching: raw rows from three sources -> the canonical `SourceRecord`.

Pure functions (no network, no Elastic). REAL column names, verified against the HF datasets-server API
and the live YC JSON on 2026-09-19:

  alvanlii/devpost-hackathon-projects (config=default, 261,940 rows)
      hackathon_id:int64, project_link:str, full_desc:str, title:str, brief_desc:str,
      team_members:str, prize:str, tags:str, __index_level_0__:int64
      !! team_members / prize / tags are *stringified Python lists* ("['c#', 'unity']", "[]").
      !! `tags` is really the Devpost "Built With" list (tech), not topical tags.
      !! there is no year/date column: join hackathon_id -> hackathons.json `submission_period_dates`.
  twangodev/devpost-hacks (config=all, 2,222 rows)
      project_id:str, hackathon:str (devpost subdomain slug), url:str, title:str, tagline:str,
      description:str, built_with:list[str], video_link:str, other_links:list[str], results:str,
      is_winner:bool, readmes:list[{repo, content, truncated}]
      !! no year/date column either: see TWANGODEV_HACKATHONS below.
  yc-oss companies: id, name, slug, former_names, website, all_locations, long_description, one_liner,
      team_size, industry, subindustry, launched_at (epoch s), tags, top_company, isHiring, nonprofit,
      batch ("Winter 2012"), status (Active|Inactive|Acquired|Public), industries, regions, stage, url

`field_provenance` values:  source = copied verbatim · normalized = deterministic reshape/join of source
fields · imputed = inferred and possibly wrong (shown with a badge in the Evidence Ledger).
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from ingest import common  # noqa: F401  (side effect: puts backend/ on sys.path so `app.*` imports work)
from ingest.parse_sections import build_pitch, clean_text, extract_tech, guess_lang, normalise_ws, parse_sections

from app.schemas.records import SourceRecord

# --------------------------------------------------------------------------------------
# Small value helpers
# --------------------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MONTH_DAY = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})")


def is_missing(value: Any) -> bool:
    """None / NaN / pandas NA / empty string."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in ("nan", "none", "null")
    try:  # pandas.NA / NaT compare unequal to themselves or raise on bool()
        return bool(value != value)
    except (TypeError, ValueError):
        return False


def parse_listish(value: Any) -> list[str]:
    """alvanlii stores lists as their Python repr ("['a', 'b']"). Accept that, real lists, arrays, CSV."""
    if value is None:
        return []
    if hasattr(value, "tolist") and not isinstance(value, str):  # numpy / pyarrow-backed arrays
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [normalise_ws(str(v)) for v in value if not is_missing(v)]
    if is_missing(value):
        return []
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple)):
                return [normalise_ws(str(v)) for v in parsed if not is_missing(v)]
        except (ValueError, SyntaxError):
            inner = re.findall(r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)\"""", text)
            return [normalise_ws(a or b) for a, b in inner if (a or b).strip()]
        return []
    return [normalise_ws(t) for t in text.split(",") if t.strip()]


def slug_from_url(url: str) -> str:
    """https://devpost.com/software/crazy-cows-game?ref=x -> crazy-cows-game"""
    path = urlsplit(url.strip()).path.rstrip("/")
    return path.rsplit("/", 1)[-1].lower()


def parse_submission_dates(text: str | None) -> tuple[int | None, dt.date | None]:
    """Devpost `submission_period_dates` -> (year, end date).

    Seen formats: "Oct 01 - Dec 04, 2024", "Mar 16 - 17, 2024", "Mar 10, 2018", "Dec 28, 2019 - Jan 05, 2020".
    The *end* of the submission period is when projects were submitted, so that is the year we keep.
    """
    if is_missing(text):
        return None, None
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", str(text))
    if not years:
        return None, None
    year = int(years[-1])
    tail = str(text).rsplit("-", 1)[-1] if "-" in str(text) else str(text)
    end: dt.date | None = None
    md = _MONTH_DAY.search(tail)
    if md and md.group(1).lower() in _MONTHS:
        month, day = _MONTHS[md.group(1).lower()], int(md.group(2))
    else:  # "Mar 16 - 17, 2024": the tail only has the day; the month comes from the head
        head = _MONTH_DAY.search(str(text))
        d2 = re.search(r"\b(\d{1,2})\b", tail)
        month = _MONTHS.get(head.group(1).lower()) if head else None
        day = int(d2.group(1)) if d2 else None
    if month and day:
        try:
            end = dt.date(year, month, day)
        except ValueError:
            end = None
    return year, end


def load_hackathons(path: str | Path) -> dict[int, dict]:
    """hackathons.json (a JSON array; same item shape as devpost.com/api/hackathons) keyed by id."""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("hackathons", [])
    return {int(h["id"]): h for h in items if "id" in h}


# Bare hosts from the "Try it out" block that say nothing about *which* project this is.
_GENERIC_HOSTS = {
    "github.com", "gitlab.com", "bitbucket.org", "youtube.com", "youtu.be", "drive.google.com", "docs.google.com",
    "play.google.com", "apps.apple.com", "devpost.com", "figma.com", "canva.com", "vimeo.com", "replit.com", "repl.it",
    "chromewebstore.google.com", "chrome.google.com", "testflight.apple.com", "colab.research.google.com", "linkedin.com",
    "twitter.com", "x.com", "facebook.com", "instagram.com", "discord.com", "discord.gg", "t.me", "medium.com", "notion.so",
    "heroku.com", "vercel.app", "netlify.app", "streamlit.app", "huggingface.co", "kaggle.com", "npmjs.com", "pypi.org",
}


def normalise_links(values: Iterable[str] | None) -> list[str]:
    """Keep informative outbound URLs (the entity resolver blocks on these); add a scheme; de-duplicate."""
    out: list[str] = []
    for v in values or []:
        v = str(v).strip().strip("<>")
        if not v or " " in v or "." not in v:
            continue
        url = v if re.match(r"^https?://", v, re.I) else f"https://{v}"
        parts = urlsplit(url)
        host = parts.netloc.lower().removeprefix("www.")
        if not host or (host in _GENERIC_HOSTS and parts.path.strip("/") == ""):
            continue
        if parts.query:  # drop tracking parameters (utm_*, ref): they break URL cross-reference blocking
            kept = [kv for kv in parts.query.split("&") if not re.match(r"^(utm_[a-z_]*|ref|ref_src|fbclid|gclid)=", kv, re.I)]
            url = parts._replace(query="&".join(kept)).geturl()
        url = url.rstrip("/")
        if url.removesuffix(".git") not in [u.removesuffix(".git") for u in out]:
            out.append(url)
    return out


def _finish(record: dict[str, Any]) -> SourceRecord:
    """Shared tail: language guess (the ingest pipeline's lang_ident overrides it when available)."""
    lang = guess_lang(record.get("pitch"))
    record["lang"] = lang
    if lang != "und":
        record["field_provenance"]["lang"] = "imputed"
    return SourceRecord(**record)


# --------------------------------------------------------------------------------------
# alvanlii/devpost-hackathon-projects
# --------------------------------------------------------------------------------------
def from_alvanlii(row: Mapping[str, Any], hackathons_by_id: Mapping[int, Mapping[str, Any]] | None = None) -> SourceRecord:
    url = str(row["project_link"]).strip()
    title = normalise_ws(str(row.get("title") or "")) or slug_from_url(url)
    tagline = None if is_missing(row.get("brief_desc")) else normalise_ws(str(row["brief_desc"]))
    description = clean_text(None if is_missing(row.get("full_desc")) else row["full_desc"])
    sections = parse_sections(description)
    prov: dict[str, str] = {"url": "source", "title": "source", "description": "normalized", "pitch": "normalized"}
    if tagline:
        prov["tagline"] = "source"

    tech, tech_prov = extract_tech(parse_listish(row.get("tags")), sections=sections)
    if tech_prov:  # the column is a stringified list, so even the structured path is a reshape
        prov["tech"] = "normalized" if tech_prov == "source" else tech_prov

    prizes = parse_listish(row.get("prize"))
    team = parse_listish(row.get("team_members"))
    traction: dict[str, Any] = {"is_winner": bool(prizes)}
    if prizes:
        traction["prize"] = prizes
    if team:
        traction["team_size"] = len(team)

    year = date = precision = None
    tags: list[str] = []
    hid = None if is_missing(row.get("hackathon_id")) else int(row["hackathon_id"])
    if hid is not None:
        traction["hackathon_id"] = str(hid)
        hk = (hackathons_by_id or {}).get(hid)
        if hk:
            traction["hackathon"] = normalise_ws(str(hk.get("title") or ""))
            if hk.get("url"):
                traction["hackathon_url"] = hk["url"]
            year, date = parse_submission_dates(hk.get("submission_period_dates"))
            if year:
                prov["year"] = "normalized"  # deterministic join on hackathon_id
                precision = "inferred"  # we know the submission window, not the project's own day
            if date:
                prov["date"] = "imputed"
            tags = [normalise_ws(t["name"]) for t in hk.get("themes") or [] if t.get("name")]
            if tags:
                prov["tags"] = "imputed"  # hackathon-level themes inherited by the project

    links = normalise_links((sections.get("try_it_out") or "").split("\n"))
    if links:
        prov["links"] = "normalized"

    return _finish(dict(
        rid=f"devpost:{slug_from_url(url)}", source="devpost", url=url, title=title, tagline=tagline,
        description=description, pitch=build_pitch(title, tagline, description, sections=sections),
        year=year, date=date, date_precision=precision, tags=tags, tech=tech, status="unknown",
        traction=traction, links=links, field_provenance=prov,
    ))


# --------------------------------------------------------------------------------------
# twangodev/devpost-hacks
# --------------------------------------------------------------------------------------
# slug -> (title, submission_period_dates, themes); verified against devpost.com/api/hackathons 2026-09-19.
TWANGODEV_HACKATHONS: dict[str, tuple[str, str, list[str]]] = {
    "cal-hacks-12-0": ("Cal Hacks 12.0", "Oct 24 - 26, 2025", ["Beginner Friendly", "Machine Learning/AI", "Open Ended"]),
    "hackgt-12": ("HackGT 12: Midnight at the Museum", "Sep 27 - 28, 2025", ["Beginner Friendly", "Social Good"]),
    "hacktech-by-caltech-2026": ("Hacktech by Caltech 2026", "Apr 25 - 26, 2026", ["Cybersecurity", "Machine Learning/AI", "Open Ended"]),
    "madhacks": ("MadHacks Fall 2024", "Nov 09 - 10, 2024", ["Open Ended", "Beginner Friendly"]),
    "madhacks-fall-2025": ("MadHacks Fall 2025", "Nov 22 - 23, 2025", ["Open Ended"]),
    "pennapps-xxv": ("PennApps XXV", "Sep 20 - 22, 2024", ["Beginner Friendly", "Open Ended", "Social Good"]),
    "treehacks-2024": ("TreeHacks 2024", "Feb 17 - 18, 2024", ["Open Ended"]),
    "treehacks-2025": ("TreeHacks 2025", "Feb 15 - 16, 2025", ["Open Ended"]),
    "treehacks-2026": ("TreeHacks 2026", "Feb 14 - 15, 2026", ["Machine Learning/AI", "Social Good", "Web"]),
}
_README_CAP = 4000  # chars of each README appended to the description (BM25 only; never embedded)


def from_twangodev(row: Mapping[str, Any]) -> SourceRecord:
    url = str(row["url"]).strip()
    title = normalise_ws(str(row.get("title") or "")) or slug_from_url(url)
    tagline = None if is_missing(row.get("tagline")) else normalise_ws(str(row["tagline"]))
    body = clean_text(None if is_missing(row.get("description")) else row["description"])
    sections = parse_sections(body)
    prov: dict[str, str] = {"url": "source", "title": "source", "description": "normalized", "pitch": "normalized"}
    if tagline:
        prov["tagline"] = "source"

    tech, tech_prov = extract_tech(parse_listish(row.get("built_with")), sections=sections)
    if tech_prov:
        prov["tech"] = tech_prov

    readmes = row.get("readmes")
    readmes = readmes.tolist() if hasattr(readmes, "tolist") else (readmes or [])
    links = normalise_links(parse_listish(row.get("other_links")))
    description = body
    for rm in readmes:
        repo, content = (rm or {}).get("repo"), (rm or {}).get("content")
        if repo and not any(str(repo).lower() in u.lower() for u in links):
            links.append(f"https://github.com/{repo}")
        if content:
            description += f"\n\n## README ({repo})\n\n{clean_text(content)[:_README_CAP]}"
    if links:
        prov["links"] = "source"

    is_winner = bool(row.get("is_winner")) and not is_missing(row.get("is_winner"))
    traction: dict[str, Any] = {"is_winner": is_winner}
    results = None if is_missing(row.get("results")) else normalise_ws(str(row["results"]))
    if is_winner and results:
        traction["prize"] = [re.sub(r"^winner\s+", "", results, flags=re.I)]
    if not is_missing(row.get("project_id")):
        traction["project_id"] = str(row["project_id"])

    slug = None if is_missing(row.get("hackathon")) else str(row["hackathon"]).strip()
    year = date = precision = None
    tags: list[str] = []
    if slug:
        traction["hackathon_id"] = slug
        traction["hackathon_url"] = f"https://{slug}.devpost.com/"
        known = TWANGODEV_HACKATHONS.get(slug)
        if known:
            traction["hackathon"] = known[0]
            year, date = parse_submission_dates(known[1])
            tags = list(known[2])
            prov.update(year="normalized", date="imputed")
            precision = "inferred"
            if tags:
                prov["tags"] = "imputed"
        else:
            traction["hackathon"] = slug
            m = re.search(r"(20\d{2})", slug)
            if m:
                year, precision = int(m.group(1)), "year"
                prov["year"] = "imputed"

    return _finish(dict(
        rid=f"devpost:{slug_from_url(url)}", source="devpost", url=url, title=title, tagline=tagline,
        description=description, pitch=build_pitch(title, tagline, body, sections=sections),
        year=year, date=date, date_precision=precision, tags=tags, tech=tech, status="unknown",
        traction=traction, links=links, field_provenance=prov,
    ))


# --------------------------------------------------------------------------------------
# YC companies (yc-oss.github.io/api)
# --------------------------------------------------------------------------------------
_YC_STATUS = {"active": "active", "inactive": "dead", "acquired": "acquired", "public": "active"}
_YC_BATCH = re.compile(r"^(?:(winter|summer|spring|fall|autumn)\s+(\d{4})|([wsfx]|ik)(\d{2}))$", re.I)


def yc_batch_year(batch: str | None) -> int | None:
    """'Winter 2012' | 'W12' | 'S21' | 'F24' | 'X25' | 'Spring 2025' -> year."""
    if is_missing(batch):
        return None
    m = _YC_BATCH.match(str(batch).strip())
    if not m:
        m2 = re.search(r"(20\d{2})", str(batch))
        return int(m2.group(1)) if m2 else None
    return int(m.group(2)) if m.group(2) else 2000 + int(m.group(4))


def from_yc(company: Mapping[str, Any]) -> SourceRecord:
    slug = str(company.get("slug") or "").strip().lower() or re.sub(r"[^a-z0-9]+", "-", str(company.get("name", "")).lower()).strip("-")
    title = normalise_ws(str(company.get("name") or slug))
    tagline = None if is_missing(company.get("one_liner")) else normalise_ws(str(company["one_liner"]))
    description = clean_text(None if is_missing(company.get("long_description")) else company["long_description"])
    prov: dict[str, str] = {"url": "source", "title": "source", "pitch": "normalized"}
    if tagline:
        prov["tagline"] = "source"
    if description:
        prov["description"] = "source"

    year = yc_batch_year(company.get("batch"))
    date = precision = None
    if year:
        prov["year"] = "normalized"
        precision = "year"
    launched = company.get("launched_at")
    if not is_missing(launched):
        try:
            date = dt.datetime.fromtimestamp(int(launched), tz=dt.timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            date = None
        # `launched_at` is the YC-directory launch; trust it only when it agrees with the batch year.
        if date is not None and (year is None or abs(date.year - year) <= 1):
            prov["date"] = "normalized"
            precision = "day"
            year = year or date.year
        else:
            date = None

    raw_status = str(company.get("status") or "").strip().lower()
    status = _YC_STATUS.get(raw_status, "unknown")
    if status != "unknown":
        prov["status"] = "normalized"

    tags: list[str] = []
    for t in [*parse_listish(company.get("tags")), *parse_listish(company.get("industries"))]:
        if t and t not in tags:
            tags.append(t)
    if tags:
        prov["tags"] = "source"

    links = normalise_links([company["website"]] if not is_missing(company.get("website")) else [])
    if links:
        prov["links"] = "source"

    traction: dict[str, Any] = {}
    for src_key, key in (("batch", "batch"), ("team_size", "team_size"), ("stage", "stage"), ("top_company", "top_company"),
                         ("isHiring", "is_hiring"), ("nonprofit", "nonprofit"), ("all_locations", "location")):
        if not is_missing(company.get(src_key)) and company.get(src_key) not in ([], {}):
            traction[key] = company[src_key]
    former = parse_listish(company.get("former_names"))
    if former:
        traction["former_names"] = former  # extra names the entity resolver can match on

    return _finish(dict(
        rid=f"yc:{slug}", source="yc", url=str(company.get("url") or f"https://www.ycombinator.com/companies/{slug}"),
        title=title, tagline=tagline, description=description, pitch=build_pitch(title, tagline, description),
        year=year, date=date, date_precision=precision, tags=tags, tech=[], status=status,
        traction=traction, links=links, field_provenance=prov,
    ))
