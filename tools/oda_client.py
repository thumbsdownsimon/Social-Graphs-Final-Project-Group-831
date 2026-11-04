#!/usr/bin/env python3
"""Small, polite client for the Folketing open data API (https://oda.ft.dk/api/).

Every response is cached to data-raw/oda/ with the time we fetched it, so a rerun
never hits the API twice for the same URL and we can say exactly what we collected
and when. Every request is logged to data-raw/oda/requests.log.

Rules the client enforces, because the API will not:
  - at most one request per THROTTLE_SECONDS,
  - retry with exponential backoff on network errors and 5xx,
  - `$` is sent as %24 and Danish names (Aktør, Møde) are percent-encoded,
  - fetch_all() checks that it received the number of rows the API promised.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://oda.ft.dk/api/"
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data-raw" / "oda"
THROTTLE_SECONDS = 0.5
MAX_RETRIES = 5
USER_AGENT = "DTU-02805-student-project (Social Graphs and Interactions)"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
_last_request = 0.0


def build_url(entity, **params):
    """build_url("Aktør", top=5, filter="typeid eq 5") -> percent-encoded OData URL."""
    query = "&".join(
        f"%24{key}={quote(str(value), safe='')}" for key, value in params.items()
    )
    return f"{BASE}{quote(entity, safe='/')}" + (f"?{query}" if query else "")


def get_json(url, use_cache=True):
    """GET a URL as JSON through the cache. Returns the decoded body."""
    global _last_request
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["body"]

    for attempt in range(MAX_RETRIES):
        wait = THROTTLE_SECONDS - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        try:
            response = _session.get(url, timeout=120)
        except requests.RequestException as error:
            problem = repr(error)
        else:
            if response.status_code == 200:
                body = response.json()
                fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
                path.write_text(
                    json.dumps({"url": url, "fetched_utc": fetched, "body": body},
                               ensure_ascii=False),
                    encoding="utf-8",
                )
                with open(CACHE / "requests.log", "a", encoding="utf-8") as log:
                    log.write(f"{fetched}\t{url}\n")
                return body
            problem = f"HTTP {response.status_code}"
            if response.status_code < 500:
                raise RuntimeError(f"{problem} for {url}: {response.text[:300]}")
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Gave up after {MAX_RETRIES} tries on {url}: {problem}")


def count(entity, filter=None):
    """Row count the API reports. Beware: see docs/data_recon.md on invalid filters."""
    params = {"top": 1, "inlinecount": "allpages"}
    if filter:
        params["filter"] = filter
    return int(get_json(build_url(entity, **params))["odata.count"])


def fetch_all(entity, page_size=100, **params):
    """Fetch every row of an entity, paging with $top/$skip, and verify the count."""
    rows, skip = [], 0
    expected = None
    while True:
        page = get_json(build_url(entity, top=page_size, skip=skip,
                                  inlinecount="allpages", **params))
        expected = int(page["odata.count"])
        rows.extend(page["value"])
        skip += len(page["value"])
        if not page["value"] or skip >= expected:
            break
    if len(rows) != expected:
        raise RuntimeError(f"{entity}: got {len(rows)} rows, API promised {expected}")
    return rows
