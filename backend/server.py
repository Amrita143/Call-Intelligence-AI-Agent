"""
FastAPI server for the Call Intelligence Agent.

Endpoints
  GET  /                      -> the single-page UI (frontend/)
  GET  /api/config            -> runtime info (mock vs LLM, model, supabase on/off, limits)
  GET  /api/status            -> {busy} — is a call currently being processed?
  GET  /api/samples           -> bundled sanitized sample transcripts
  POST /api/transcribe        -> audio file -> diarized transcript (AssemblyAI)
  POST /api/analyze           -> SSE stream of the workflow trace + final result
  GET  /api/runs              -> recent runs (from Supabase)
  GET  /api/runs/{id}         -> one full stored run
  GET/POST/PUT/DELETE /api/domains[...] -> domain-context registry CRUD
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent
import db
from samples import SAMPLES

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

# ── Limits / abuse guards ─────────────────────────────────────────────
MAX_AUDIO_BYTES = 200 * 1024 * 1024          # 200 MB (~ up to ~45 min of typical call audio)
MAX_TRANSCRIPT_CHARS = 100_000               # ~25k tokens; blocks runaway inputs
ALLOWED_AUDIO_EXT = {
    ".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".oga", ".opus",
    ".flac", ".webm", ".amr", ".wma", ".aiff", ".aif",
}
STALE_LOCK_SECONDS = 20 * 60                 # auto-release a lock held too long (safety net)

app = FastAPI(title="Call Intelligence Agent")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ── One-job-at-a-time processing lock ─────────────────────────────────
# The demo is single-worker; only one transcription/analysis runs at a time.
# A second request while busy gets a clean 429 instead of racing.
_proc_lock = threading.Lock()
_proc_since = 0.0


def _acquire_or_429(what: str):
    global _proc_since
    # reclaim a stale lock (e.g. a client disconnected mid-stream and the
    # generator never finished) so the app can't wedge permanently.
    if _proc_lock.locked() and _proc_since and (time.time() - _proc_since) > STALE_LOCK_SECONDS:
        try:
            _proc_lock.release()
        except RuntimeError:
            pass
    if not _proc_lock.acquire(blocking=False):
        raise HTTPException(429, "A call is already being processed. Please wait for it to finish, then try again.")
    _proc_since = time.time()


def _release():
    global _proc_since
    _proc_since = 0.0
    if _proc_lock.locked():
        try:
            _proc_lock.release()
        except RuntimeError:
            pass


class AnalyzeRequest(BaseModel):
    transcript: str
    meeting_date: str | None = None
    source_name: str | None = None
    source_type: str = "transcript"


@app.get("/api/config")
def config():
    return {
        "mock_mode": not agent.USE_LLM,
        "model": agent.MODEL if agent.USE_LLM else "mock (deterministic)",
        "supabase_enabled": db.ENABLED,
        "assemblyai_enabled": bool(os.getenv("ASSEMBLYAI_API_KEY", "").strip()),
        "domains": {k: v["agent"] for k, v in agent.get_domains().items()},
        "limits": {
            "max_audio_mb": MAX_AUDIO_BYTES // (1024 * 1024),
            "max_transcript_chars": MAX_TRANSCRIPT_CHARS,
            "allowed_audio_ext": sorted(ALLOWED_AUDIO_EXT),
        },
    }


@app.get("/api/status")
def status():
    return {"busy": _proc_lock.locked()}


@app.get("/api/samples")
def get_samples():
    return [
        {"key": k, "label": v["label"], "meeting_date": v["meeting_date"], "transcript": v["transcript"]}
        for k, v in SAMPLES.items()
    ]


# ── Transcription ─────────────────────────────────────────────────────
@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not os.getenv("ASSEMBLYAI_API_KEY", "").strip():
        raise HTTPException(400, "Audio transcription is off (no AssemblyAI key). Paste a transcript instead.")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(
            415, f"Unsupported audio type '{ext or 'unknown'}'. Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXT))}.")

    _acquire_or_429("transcription")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext or ".wav")
    try:
        # stream to disk with a hard size cap (never load an unbounded file into memory)
        size = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_AUDIO_BYTES:
                raise HTTPException(413, f"Audio exceeds the {MAX_AUDIO_BYTES // (1024*1024)} MB limit.")
            tmp.write(chunk)
        tmp.close()
        if size == 0:
            raise HTTPException(400, "Uploaded file is empty.")
        out = agent.transcribe_audio(tmp.name)
        return {"transcript": out["transcript"], "source_name": file.filename, "utterances": len(out["utterances"])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        _release()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _sse(obj) -> str:
    return f"data: {json.dumps(obj)}\n\n"


# ── Analysis (SSE) ────────────────────────────────────────────────────
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    text = req.transcript.strip()
    if not text:
        raise HTTPException(400, "Empty transcript.")
    if len(req.transcript) > MAX_TRANSCRIPT_CHARS:
        raise HTTPException(
            413, f"Transcript is too long ({len(req.transcript):,} chars). "
                 f"Limit is {MAX_TRANSCRIPT_CHARS:,} characters.")

    _acquire_or_429("analysis")

    def stream():
        result, trace = None, []
        try:
            for event in agent.run_stream(req.transcript, req.meeting_date):
                if event.get("node") == "result":
                    result = event.get("result")
                else:
                    trace.append(event)      # keep the trace for persistence
                yield _sse(event)
            if result:
                saved = db.save_run(
                    source_type=req.source_type,
                    source_name=req.source_name,
                    meeting_date=req.meeting_date,
                    transcript=req.transcript,
                    result=result,
                    trace=trace,
                )
                yield _sse({"node": "saved", "title": "Saved to Supabase", "status": "info",
                            "saved": bool(saved), "id": saved.get("id") if saved else None})
        finally:
            _release()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Run history ───────────────────────────────────────────────────────
@app.get("/api/runs")
def runs():
    return db.list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    row = db.get_run(run_id)
    if not row:
        raise HTTPException(404, "Not found.")
    return row


# ── Domain-context registry CRUD ──────────────────────────────────────
class DomainPayload(BaseModel):
    key: str
    agent: str
    description: str
    context: str


@app.get("/api/domains")
def domains_list():
    return agent.get_domains()


@app.post("/api/domains")
def domains_upsert(d: DomainPayload):
    key = agent.upsert_domain(d.key, d.agent, d.description, d.context)
    if not key:
        raise HTTPException(400, "Invalid domain key, or a built-in/reserved key.")
    return {"ok": True, "key": key}


@app.delete("/api/domains/{key}")
def domains_delete(key: str):
    ok = agent.delete_domain(key)
    if not ok:
        raise HTTPException(400, "Cannot delete a built-in domain (or it does not exist).")
    return {"ok": True}


# ---- static frontend (mounted last so /api/* wins) ----
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
