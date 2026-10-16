"""Collect daily Wikipedia pageviews from the Wikimedia REST API.

No API key, no account, generous rate limits, and a documented terms of use —
which makes it one of the few genuinely open sources you can build a portfolio
project on without a scraper that breaks or a licence you cannot honour.

What makes this more than `requests.get` in a loop:

  * retries with exponential backoff and jitter, and it distinguishes a
    retryable 429/5xx from a permanent 404 instead of hammering a dead endpoint
  * an on-disk cache keyed by request, so re-running the analysis does not
    re-hit the API and the results stay reproducible
  * a provenance sidecar recording the exact URLs, the fetch timestamp and the
    API version, because "where did this data come from" is the first question
    anyone asks about a chart six months later
  * a declared User-Agent, which the Wikimedia API policy requires

Usage:
    python 02-python-pageviews/src/collect.py \
        --start 2023-01-01 --end 2025-12-31 --out 02-python-pageviews/data

API docs: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/
Terms:    https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

API_ROOT = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
API_VERSION = "rest_v1"

# A contactable User-Agent is required by Wikimedia policy. Replace the URL with
# your own repository before running this against the live API.
USER_AGENT = (
    "dataAnalyst-portfolio/1.0 "
    "(https://github.com/Phrheke/dataAnalyst-portfolio) python-urllib"
)

# The articles. Chosen to span three behavioural patterns that should be
# distinguishable if the weekday hypothesis holds: professional/technical topics
# people read at work, a tooling topic, and a leisure topic as a control.
DEFAULT_ARTICLES = {
    "Data_analysis": "professional",
    "Statistics": "professional",
    "Machine_learning": "professional",
    "SQL": "tooling",
    "Python_(programming_language)": "tooling",
    "Microsoft_Excel": "tooling",
    "Association_football": "leisure",
    "Netflix": "leisure",
}

MAX_RETRIES = 5
BASE_BACKOFF = 1.5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Provenance:
    """Everything needed to answer 'where did this number come from'."""

    fetched_at_utc: str
    api_root: str
    api_version: str
    user_agent: str
    articles: dict
    start: str
    end: str
    project: str
    access: str
    agent: str
    urls: list
    rows: int
    from_cache: list


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def fetch_json(url: str, cache_dir: Path, opener=None) -> tuple[dict, bool]:
    """GET a URL with retries and an on-disk cache.

    Returns (payload, came_from_cache).

    A 404 means the article has no data for that range; it is returned as an
    empty payload rather than raised, because one missing article should not
    abort a run over eight of them. 429 and 5xx are retried with exponential
    backoff plus jitter — the jitter matters when several requests are retrying
    together, or they re-collide on exactly the same schedule.
    """
    cached = _cache_path(cache_dir, url)
    if cached.exists():
        return json.loads(cached.read_text()), True

    opener = opener or urllib.request.urlopen
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode())
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(payload))
            return payload, False
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                return {"items": []}, False
            if exc.code not in RETRYABLE_STATUS:
                raise
            # Honour Retry-After when the server sends one.
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else (
                BASE_BACKOFF**attempt + random.uniform(0, 0.5)
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            delay = BASE_BACKOFF**attempt + random.uniform(0, 0.5)

        if attempt < MAX_RETRIES - 1:
            time.sleep(delay)

    raise RuntimeError(f"giving up on {url} after {MAX_RETRIES} attempts") from last_error


def build_url(article: str, start: date, end: date, project: str,
              access: str, agent: str) -> str:
    return (
        f"{API_ROOT}/{project}/{access}/{agent}/"
        f"{urllib.request.quote(article, safe='')}/daily/"
        f"{start:%Y%m%d}/{end:%Y%m%d}"
    )


def collect(articles: dict, start: date, end: date, out_dir: Path,
            project: str = "en.wikipedia", access: str = "all-access",
            agent: str = "user", opener=None) -> tuple[list[dict], Provenance]:
    """Fetch every article and return tidy rows plus provenance.

    `agent="user"` excludes bots and spiders. This is not a detail: including
    automated traffic would swamp exactly the weekday/weekend signal the
    analysis is looking for, because crawlers do not take weekends off.
    """
    cache_dir = out_dir / "cache"
    rows: list[dict] = []
    urls: list[str] = []
    from_cache: list[str] = []

    for article, topic_class in articles.items():
        url = build_url(article, start, end, project, access, agent)
        urls.append(url)
        payload, cached = fetch_json(url, cache_dir, opener=opener)
        if cached:
            from_cache.append(article)

        items = payload.get("items", [])
        if not items:
            print(f"  WARNING no data for {article}")
        for item in items:
            # Timestamps arrive as YYYYMMDD00 -- the trailing 00 is the hour
            # granularity marker for daily data.
            stamp = item["timestamp"][:8]
            rows.append({
                "article": item.get("article", article),
                "topic_class": topic_class,
                "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}",
                "views": int(item["views"]),
            })
        print(f"  {article:<32} {len(items):>5} days{'  (cache)' if cached else ''}")
        if not cached:
            time.sleep(0.2)  # be a polite client even though the limit is generous

    prov = Provenance(
        fetched_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        api_root=API_ROOT,
        api_version=API_VERSION,
        user_agent=USER_AGENT,
        articles=articles,
        start=start.isoformat(),
        end=end.isoformat(),
        project=project,
        access=access,
        agent=agent,
        urls=urls,
        rows=len(rows),
        from_cache=from_cache,
    )
    return rows, prov


def write(rows: list[dict], prov: Provenance, out_dir: Path) -> None:
    import csv

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "pageviews.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["article", "topic_class", "date", "views"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["article"], r["date"])))
    (out_dir / "provenance.json").write_text(json.dumps(asdict(prov), indent=2))
    print(f"\nWrote {path} ({len(rows):,} rows) and provenance.json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2023-01-01", type=lambda s: date.fromisoformat(s))
    ap.add_argument("--end", default="2025-12-31", type=lambda s: date.fromisoformat(s))
    ap.add_argument("--out", default="02-python-pageviews/data", type=Path)
    ap.add_argument("--project", default="en.wikipedia")
    ap.add_argument("--agent", default="user", choices=["user", "all-agents", "spider"])
    args = ap.parse_args()

    if args.start > args.end:
        raise SystemExit("--start must be on or before --end")

    print(f"Collecting {len(DEFAULT_ARTICLES)} articles, "
          f"{args.start} to {args.end}, agent={args.agent}")
    rows, prov = collect(DEFAULT_ARTICLES, args.start, args.end, args.out,
                         project=args.project, agent=args.agent)
    write(rows, prov, args.out)


if __name__ == "__main__":
    main()
