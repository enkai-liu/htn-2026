"""Shared HTTP behaviour for live sources: 8 s timeout, 2 retries with backoff, then the caller marks the source failed."""
from __future__ import annotations

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

USER_AGENT = "WhitespaceHTN2026/0.1 (hackathon research project; github.com/enkai-liu/htn-2026)"
TIMEOUT = httpx.Timeout(8.0, connect=4.0)


class SourceError(RuntimeError):
    pass


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 425, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


async def get_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=3),
                                           retry=retry_if_exception(_retryable), reraise=True):
            with attempt:
                async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT, **(headers or {})}) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    return resp.json()
    except httpx.HTTPStatusError as exc:  # 403/429 are not retried: we back off instead of pushing through limits
        raise SourceError(f"HTTP {exc.response.status_code} from {httpx.URL(url).host}") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise SourceError(f"{type(exc).__name__} from {httpx.URL(url).host} after 3 attempts") from exc
    raise SourceError("unreachable")
