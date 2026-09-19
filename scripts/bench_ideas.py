"""Sanity benchmark: do scores order ideas sensibly, from cliche to novel?

Runs each idea through a live backend and compares the ranking with the expected one (Spearman rho >= 0.8 passes).
Needs the backend running with real keys:  make backend  &&  backend/.venv/bin/python scripts/bench_ideas.py

    --base http://localhost:8000   --only 1,5   --axis headline|crowding   --out docs/benchmarks.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# (id, expected originality band, pitch). Pitches are >= 250 chars so the Voice axis can run too.
IDEAS: list[tuple[int, tuple[int, int], str]] = [
    (1, (0, 20), "StudyBuddy AI is a study assistant for students. You upload your lecture notes and PDFs, and it uses retrieval augmented "
                 "generation to answer questions about them, generate flashcards and quizzes, and summarise each chapter so you can revise "
                 "faster before exams. It has a chat interface and tracks which topics you are weak on."),
    (2, (0, 25), "FridgeChef lets you take a photo of the inside of your fridge, uses computer vision to detect the ingredients you have, and "
                 "then suggests recipes you can cook with them using a large language model. It reduces food waste, builds a shopping list "
                 "for missing items and lets you filter recipes by diet and cooking time."),
    (3, (0, 25), "MindJournal is an AI journaling app that acts like a supportive therapist. You write about your day and it responds with "
                 "empathetic reflections, tracks your mood over time with sentiment analysis, highlights recurring stress patterns and "
                 "suggests breathing exercises and coping strategies when it detects that you are feeling anxious."),
    (4, (25, 40), "SignBridge translates American Sign Language into text in real time using your laptop webcam. A hand-pose model tracks "
                  "finger landmarks, a classifier recognises letters and common signs, and the recognised words are shown as captions so "
                  "deaf and hearing people can talk in a video call without an interpreter."),
    (5, (25, 45), "HackCheck tells you whether your hackathon project idea has already been built. You type your idea, it extracts keywords "
                  "with a language model, searches Devpost for similar past submissions and gives you an originality score out of one hundred "
                  "with a short explanation and links to the most similar projects."),
    (6, (45, 65), "GreenCI is a scheduler for continuous integration pipelines that is aware of the carbon intensity of the electricity grid. "
                  "Non-urgent builds and test suites are delayed or moved to the data centre region where power is currently cleanest, using "
                  "live grid data, and developers see how many grams of CO2 each merge request saved."),
    (7, (60, 80), "Blame Game turns a team's git history into a murder mystery party game. It mines commits, reverts and blame data to "
                  "generate a whodunnit where a production outage is the crime, teammates are suspects with alibis drawn from their real "
                  "commit timestamps, and players interrogate the repository to find which change caused the incident."),
    (8, (70, 100), "FeelCast is a shape-changing tactile display that lets blind people feel the uncertainty in a weather forecast. An array of "
                   "small actuated pins renders the forecast as a raised surface where height is the predicted value and the vibration "
                   "frequency of each pin encodes how much the forecast models disagree, so confidence can be read with the fingertips."),
]
EDGE_CASES = [
    ("short", "Uber for dogs."),  # < 250 chars: Voice must say "too short", crowding still computed
    ("spanish", "Una aplicación que ayuda a los estudiantes a encontrar compañeros de estudio en su universidad según sus asignaturas, "
                "horarios y estilo de aprendizaje, con un chat integrado, salas de estudio virtuales y recordatorios automáticos para "
                "las sesiones de grupo antes de los exámenes finales de cada semestre."),
]


def run_idea(base: str, text: str, timeout: float = 240) -> dict:
    with httpx.Client(timeout=30) as c:
        run_id = c.post(f"{base}/api/runs", json={"idea_text": text}).raise_for_status().json()["run_id"]
    report, errors, started = None, [], time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=10)) as c, c.stream("GET", f"{base}/api/runs/{run_id}/events") as r:
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if ev["type"] == "error":
                errors.append(ev["data"]["message"])
                if not ev["data"].get("recoverable"):
                    break
            if ev["type"] == "run.finished":
                report = ev["data"]["report"]
                break
    return {"run_id": run_id, "report": report, "errors": errors, "seconds": round(time.monotonic() - started, 1)}


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--only", default="")
    ap.add_argument("--axis", default="headline", choices=["headline", "crowding"])
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    only = {int(x) for x in a.only.split(",") if x}
    rows = []
    for iid, band, text in IDEAS:
        if only and iid not in only:
            continue
        res = run_idea(a.base, text)
        sc = (res["report"] or {}).get("scores") or {}
        value = sc.get("headline") if a.axis == "headline" else (sc.get("crowding") or {}).get("score")
        if value is None:  # abstained headline: fall back to crowding so ordering can still be checked
            value = (sc.get("crowding") or {}).get("score")
        top = [e["canonical_name"] for e in ((res["report"] or {}).get("entities") or [])[:3]]
        rows.append({"id": iid, "expected": band, "score": value, "confidence": sc.get("confidence"), "abstain": (sc.get("abstain") or {}).get("active"),
                     "top": top, "seconds": res["seconds"], "errors": res["errors"][:2]})
        print(f"#{iid} expected {band} -> {value}  conf={sc.get('confidence')}  {res['seconds']}s  top={top}  errors={res['errors'][:1]}", flush=True)
    scored = [r for r in rows if r["score"] is not None]
    rho = spearman([sum(r["expected"]) / 2 for r in scored], [r["score"] for r in scored]) if len(scored) >= 3 else float("nan")
    in_band = sum(r["expected"][0] <= r["score"] <= r["expected"][1] for r in scored)
    print(f"\nSpearman rho = {rho:.2f} over {len(scored)} ideas (pass >= 0.80); {in_band}/{len(scored)} inside the expected band")
    if a.out:
        lines = ["# Benchmarks", "", f"Spearman rho = **{rho:.2f}** over {len(scored)} ideas (pass >= 0.80); {in_band}/{len(scored)} inside the expected band.", "",
                 "| # | expected | score | confidence | abstained | top neighbours | seconds |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['id']} | {r['expected'][0]}–{r['expected'][1]} | {r['score']} | {r['confidence']} | {r['abstain']} | {', '.join(r['top'])} | {r['seconds']} |" for r in rows]
        Path(a.out).write_text("\n".join(lines) + "\n")
    return 0 if rho >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
