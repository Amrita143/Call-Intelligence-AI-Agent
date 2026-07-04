"""
Supabase persistence (thin REST wrapper — no extra SDK needed).

Every completed run is saved to the `public.runs` table so the UI can show a
history and reopen past results. If Supabase is unreachable or not configured,
the app keeps working (persistence is best-effort and never blocks a run).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
# Service role for server-side writes; falls back to anon key.
_KEY = os.getenv("SUPABASE_SERVICE_ROLE_SECRET") or os.getenv("SUPABASE_PUBLIC_ANON_KEY", "")
ENABLED = bool(SUPABASE_URL and _KEY)


def _request(method: str, path: str, body=None, extra_headers=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "call-intelligence-agent",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else None


def save_run(*, source_type, source_name, meeting_date, transcript, result, trace=None) -> dict | None:
    """Insert one run. Returns the stored row (with id) or None on failure."""
    if not ENABLED:
        return None
    row = {
        "source_type": source_type,
        "source_name": source_name,
        "meeting_date": meeting_date or None,
        "domain": result.get("domain"),
        "domain_rationale": result.get("domain_rationale"),
        "tag": result.get("tag"),
        "summary": result.get("summary"),
        "segment_count": result.get("segment_count"),
        "mock_mode": result.get("mock_mode", False),
        "transcript": transcript,
        "result": result,
        "trace": trace or [],
        "human_review_count": len(result.get("items_needing_human_review", [])),
    }
    try:
        out = _request("POST", "runs", body=row, extra_headers={"Prefer": "return=representation"})
        return out[0] if isinstance(out, list) and out else out
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[db] save_run failed: {e}")
        return None


def list_runs(limit: int = 25) -> list:
    if not ENABLED:
        return []
    cols = "id,created_at,source_type,source_name,domain,tag,segment_count,mock_mode,human_review_count"
    try:
        return _request("GET", f"runs?select={cols}&order=created_at.desc&limit={limit}") or []
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[db] list_runs failed: {e}")
        return []


def get_run(run_id: str) -> dict | None:
    if not ENABLED:
        return None
    try:
        out = _request("GET", f"runs?id=eq.{run_id}&select=*&limit=1")
        return out[0] if out else None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[db] get_run failed: {e}")
        return None


# ── Domain-context registry ───────────────────────────────────────────
def list_domains() -> list:
    if not ENABLED:
        return []
    try:
        return _request("GET", "domains?select=*&order=created_at.asc") or []
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[db] list_domains failed: {e}")
        return []


def upsert_domain(key: str, agent: str, description: str, context: str) -> bool:
    if not ENABLED:
        return False
    row = {"key": key, "agent": agent, "description": description, "context": context}
    try:
        # upsert on primary key
        _request("POST", "domains", body=row,
                 extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[db] upsert_domain failed: {e}")
        return False


def delete_domain(key: str) -> bool:
    if not ENABLED:
        return False
    try:
        _request("DELETE", f"domains?key=eq.{key}")
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"[db] delete_domain failed: {e}")
        return False
