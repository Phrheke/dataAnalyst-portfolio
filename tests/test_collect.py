"""Tests for the pageviews collector, with no network access.

The retry and caching logic is the part most likely to be wrong and the part
hardest to check by running it against the real API: you cannot ask Wikimedia
to return a 503 on demand. So the HTTP layer is injected and the failures are
simulated.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02-python-pageviews" / "src"))

import collect  # noqa: E402


class FakeResponse(io.BytesIO):
    """Minimal stand-in for an http.client.HTTPResponse used as a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def payload(article: str, days: int = 3) -> bytes:
    items = [
        {"article": article, "timestamp": f"2025010{i + 1}00", "views": 100 + i}
        for i in range(days)
    ]
    return json.dumps({"items": items}).encode()


def make_opener(script):
    """Build an opener that replays `script`: each entry is bytes or an Exception."""
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        step = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(step, Exception):
            raise step
        return FakeResponse(step)

    opener.calls = calls
    return opener


# -----------------------------------------------------------------------------

def test_url_is_built_correctly():
    url = collect.build_url("Data_analysis", date(2025, 1, 1), date(2025, 1, 31),
                            "en.wikipedia", "all-access", "user")
    assert url.endswith("/Data_analysis/daily/20250101/20250131")
    assert "/en.wikipedia/all-access/user/" in url


def test_article_names_are_url_encoded():
    url = collect.build_url("Python_(programming_language)", date(2025, 1, 1),
                            date(2025, 1, 2), "en.wikipedia", "all-access", "user")
    assert "%28programming_language%29" in url


def test_user_agent_is_sent(tmp_path):
    """Wikimedia policy requires a contactable User-Agent. Omitting it gets you blocked."""
    seen = {}

    def opener(request, timeout=None):
        seen["ua"] = request.get_header("User-agent")
        return FakeResponse(payload("X"))

    collect.fetch_json("https://example.test/a", tmp_path, opener=opener)
    assert seen["ua"] == collect.USER_AGENT
    assert "http" in seen["ua"]  # contains a contact URL


def test_successful_fetch_is_cached(tmp_path):
    opener = make_opener([payload("Data_analysis")])
    url = "https://example.test/data_analysis"

    first, cached_first = collect.fetch_json(url, tmp_path, opener=opener)
    assert cached_first is False
    assert len(first["items"]) == 3

    second, cached_second = collect.fetch_json(url, tmp_path, opener=opener)
    assert cached_second is True
    assert second == first
    # The cache must prevent a second HTTP call entirely.
    assert len(opener.calls) == 1


def test_different_urls_get_different_cache_entries(tmp_path):
    opener = make_opener([payload("A"), payload("B")])
    collect.fetch_json("https://example.test/a", tmp_path, opener=opener)
    collect.fetch_json("https://example.test/b", tmp_path, opener=opener)
    assert len(opener.calls) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_404_returns_empty_rather_than_raising(tmp_path):
    """A missing article must not abort a run over eight of them."""
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    opener = make_opener([err])
    result, cached = collect.fetch_json("https://example.test/missing", tmp_path, opener=opener)
    assert result == {"items": []}
    assert cached is False
    # And it must not retry a permanent failure.
    assert len(opener.calls) == 1


def test_permanent_4xx_is_raised(tmp_path):
    """A 403 means we are doing something wrong; retrying will not fix it."""
    err = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    opener = make_opener([err])
    with pytest.raises(urllib.error.HTTPError):
        collect.fetch_json("https://example.test/forbidden", tmp_path, opener=opener)
    assert len(opener.calls) == 1


def test_503_is_retried_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    err = urllib.error.HTTPError("u", 503, "Unavailable", {}, None)
    opener = make_opener([err, err, payload("Recovered")])
    result, _ = collect.fetch_json("https://example.test/flaky", tmp_path, opener=opener)
    assert len(result["items"]) == 3
    assert len(opener.calls) == 3


def test_429_honours_retry_after(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr(collect.time, "sleep", lambda s: delays.append(s))

    class Headers(dict):
        def get(self, k, default=None):
            return super().get(k, default)

    err = urllib.error.HTTPError("u", 429, "Too Many", Headers({"Retry-After": "7"}), None)
    opener = make_opener([err, payload("OK")])
    collect.fetch_json("https://example.test/limited", tmp_path, opener=opener)
    assert delays and delays[0] == 7.0


def test_gives_up_after_max_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    err = urllib.error.HTTPError("u", 500, "Boom", {}, None)
    opener = make_opener([err] * (collect.MAX_RETRIES + 2))
    with pytest.raises(RuntimeError, match="giving up"):
        collect.fetch_json("https://example.test/dead", tmp_path, opener=opener)
    assert len(opener.calls) == collect.MAX_RETRIES


def test_network_error_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    opener = make_opener([urllib.error.URLError("dns"), payload("OK")])
    result, _ = collect.fetch_json("https://example.test/dns", tmp_path, opener=opener)
    assert len(result["items"]) == 3


def test_collect_parses_timestamps_and_tidies_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    articles = {"Data_analysis": "professional", "Netflix": "leisure"}
    opener = make_opener([payload("Data_analysis"), payload("Netflix")])
    rows, prov = collect.collect(articles, date(2025, 1, 1), date(2025, 1, 3),
                                 tmp_path, opener=opener)
    assert len(rows) == 6
    # The API's YYYYMMDD00 form must become an ISO date.
    assert rows[0]["date"] == "2025-01-01"
    assert all(isinstance(r["views"], int) for r in rows)
    assert {r["topic_class"] for r in rows} == {"professional", "leisure"}
    assert prov.rows == 6
    assert len(prov.urls) == 2


def test_provenance_records_what_is_needed_to_reproduce(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    opener = make_opener([payload("Data_analysis")])
    _, prov = collect.collect({"Data_analysis": "professional"},
                              date(2025, 1, 1), date(2025, 1, 3), tmp_path, opener=opener)
    assert prov.api_version == "rest_v1"
    assert prov.agent == "user"       # bots excluded by default -- see docstring
    assert prov.start == "2025-01-01"
    assert prov.fetched_at_utc.endswith(("+00:00", "Z"))
    assert prov.user_agent == collect.USER_AGENT


def test_default_agent_excludes_bots():
    """If this ever defaults to all-agents, the weekday signal gets swamped."""
    import inspect
    sig = inspect.signature(collect.collect)
    assert sig.parameters["agent"].default == "user"


def test_write_produces_csv_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    opener = make_opener([payload("Data_analysis")])
    rows, prov = collect.collect({"Data_analysis": "professional"},
                                 date(2025, 1, 1), date(2025, 1, 3), tmp_path, opener=opener)
    out = tmp_path / "out"
    collect.write(rows, prov, out)
    csv_text = (out / "pageviews.csv").read_text()
    assert csv_text.startswith("article,topic_class,date,views")
    assert json.loads((out / "provenance.json").read_text())["rows"] == 3
