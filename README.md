# Call Intelligence Agent

An agent-led meeting/call intelligence workflow. Give it a call **transcript or audio**
and it returns structured, **source-grounded** notes a team or QA reviewer can trust:
summary, decisions, action items (owners + resolved dates), blockers, compliance
observations (Red/Yellow/Green), and an explicit **human-review queue** — every item
cited back to the exact transcript line it came from.

This repo turns the original notebook (`app.ipynb`) into a demoable web app with a
FastAPI backend and a clean single-page UI, backed by Supabase for run history. The
notebook and design docs are unchanged and remain the source of truth for the logic.

> **The problem, in one line:** don't "summarise a call" — turn a call into notes a
> person can rely on, where every claim points to a real line and anything uncertain
> goes to a human instead of being guessed.

---

## What you see in the UI

- **Input** — paste a transcript, load one of four sanitized samples, **or** upload audio.
  You provide *one* input, not both; audio is staged and transcribed when you hit Analyze.
- **Agent trace** — the workflow streams **live, node by node** (segment → route →
  extract ‖ review → ground → assemble), so you watch the domain agent *join the call*,
  bring the right rulebook, and process it in real time. **Expand any step** to inspect its
  raw output (segments, routing rationale, extraction/review objects). This is the
  observability view.
- **Results** — structured output with clearly delineated sections (Decisions, Action items,
  Blockers, Compliance, Human review, Next steps). Each item shows its **grounded evidence**
  (rebuilt from the transcript, not the model) with the exact line ids. Click any evidence
  block to highlight those lines in the **Transcript** tab.
- **Needs human review** — the human-in-the-loop queue, each item with a reason and category.
- **Domains** — the domain-context registry. See the built-in domains and **add / delete your
  own** so the agent applies the right rulebook to new call types, with no code change.
- **History** — every run (results **and** its full agent trace + transcript) is persisted to
  **Supabase** and can be reopened, trace and all.

---

## Architecture

The full rationale is in [`architectural_plan_and_decisions.md`](architectural_plan_and_decisions.md).
In short, it's a **LangGraph workflow** (not an autonomous agent — the path is fixed so
the output stays auditable) using two patterns from Anthropic's *Building Effective Agents*:

```
segment_transcript ──▶ classify_domain ──┬─▶ extract_items ──────┐
   (plain code,          (routing: picks  │                       ├─▶ verify_grounding ─▶ assemble_output
    numbers lines)        the domain +     └─▶ review_compliance ──┘   (deterministic gate)
                          its rulebook)        (parallel section)
```

- **Two LLM agents on the same call.** An **extraction agent** records what happened; a
  domain-specific **review/compliance agent** reads it critically against that domain's
  rulebook and escalates.
- **Grounding is plain Python, not the model.** Line numbers are assigned before the model
  sees anything; the model may only *point at* line ids; `verify_grounding` rebuilds each
  item's evidence from those lines and routes any fabricated citation to human review.
- **Dates** are resolved by the model against a single anchor (the meeting date) into
  concrete `YYYY-MM-DD`; too-vague phrases are left blank for a human.
- **Domains are swappable context** — built-in domains live in `backend/agent.py`; custom ones
  are stored in Supabase and merged in at run time. Add / update / delete them from the
  **Domains** tab (or the `/api/domains` endpoints) and the router picks them up on the next
  run; no prompt or code changes needed.

### Guardrails & limits

- **One input at a time** — supplying both an audio file and transcript text is rejected.
- **One job at a time** — a server-side lock means a second analysis/transcription while one is
  running gets a clean `429` (with a stale-lock safety release); the UI shows a busy banner and
  polls `/api/status`. Refreshing mid-run just lets the in-flight run finish server-side.
- **Upload limits** — audio capped at **200 MB** with an extension allowlist (wav/mp3/m4a/mp4/
  aac/ogg/flac/webm/…); transcripts capped at **100,000 characters**. Limits are surfaced via
  `/api/config` and enforced both client- and server-side.

### Files (kept deliberately small)

```
Call Intelligence Agent/
├─ backend/
│  ├─ agent.py          # the workflow: schemas, domains, LLM nodes, LangGraph graph,
│  │                    #   streaming trace runner, AssemblyAI transcription
│  ├─ mock_engine.py    # deterministic no-key fallback (LLM-optional mode)
│  ├─ server.py         # FastAPI: SSE analyze, samples, transcribe, runs; serves the UI
│  ├─ db.py             # Supabase persistence (thin REST, best-effort)
│  ├─ samples.py        # 4 sanitized sample transcripts
│  ├─ schema.sql        # Supabase table (already applied to the bundled project)
│  ├─ test_pipeline.py  # validation/eval suite (runs with no API key)
│  └─ requirements.txt
├─ frontend/            # index.html · styles.css · app.js  (no build step)
├─ Dockerfile · docker-compose.yml
├─ app.ipynb            # original notebook (unchanged)
├─ architectural_plan_and_decisions.md · problem_statement.md   (unchanged)
└─ .env                 # keys (git-ignore in a real repo)
```

---

## Run it

### Option A — Docker (one command)

```bash
docker compose up --build
```
Open **http://localhost:8000**. Keys are read from `.env`; with none it runs in mock mode.

### Option B — Local (Python 3.11+)

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn server:app --app-dir . --host 127.0.0.1 --port 8000
```
Open **http://localhost:8000**.

### No API key? It still runs.

If `OPENAI_API_KEY` is absent (or you set `FORCE_MOCK=1`), the app switches to a
**deterministic mock engine**: line numbering, routing, grounding, the human-review gate,
Supabase persistence and the full UI all work, and the four bundled samples return rich,
hand-authored outputs that mirror the notebook's expected results. Add an `OPENAI_API_KEY`
for live extraction on arbitrary transcripts. Audio transcription additionally needs
`ASSEMBLYAI_API_KEY`.

Environment variables (all optional): `OPENAI_API_KEY`, `MODEL` (default `gpt-4.1`),
`ASSEMBLYAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_SECRET`
(or `SUPABASE_PUBLIC_ANON_KEY`), `FORCE_MOCK`.

### Deploy it (free)

The app is one FastAPI service (API + UI) in a `$PORT`-aware Docker image, so it deploys to
a free container host in a few clicks. See **[DEPLOYMENT.md](DEPLOYMENT.md)** for a
step-by-step Railway guide.

---

## Tests / validation

A no-key eval suite checks the invariants that make the output trustworthy — domain
routing, every item grounded to a real line, sharp date resolution (`"15th of next
month" → 2026-08-15`, `"Friday" → 2026-07-03`, `"end of next week" → 2026-07-10`), the
"don't guess an owner" rule, a populated human-review queue, and the anti-hallucination
gate catching a fabricated citation.

```bash
cd backend
FORCE_MOCK=1 python test_pipeline.py     # or: python -m pytest test_pipeline.py -q
```

---

## Reviewer instructions (2-minute demo)

1. `docker compose up --build` → open http://localhost:8000.
2. Click the **Debt collection — settlement split** sample → **Analyze call**.
3. Watch the **Agent trace** stream: the *Collections Compliance Specialist* joins, extraction
   and review run, then grounding verifies citations.
4. In **Results**, note the settlement split routed to **Needs human review** (beyond
   authority), the second $700 installment dated **2026-08-15**, and the tape-disclosure /
   mini-Miranda marked **Green**. Click any **grounded evidence** block to highlight its
   source lines in the **Transcript** tab.
5. Open **History** — the run is saved in Supabase; reopen it.
6. Optional: run `FORCE_MOCK=1 python backend/test_pipeline.py` for the validation checklist.

---

## Assumptions, tradeoffs & privacy boundaries

- **One call per run; no cross-meeting memory** (explicitly out of scope).
- **Workflow over autonomous agent** — chosen for auditability; the fixed path is the feature.
- **Grounding stops fabricated line ids, not a real-but-slightly-wrong one** — but the
  rebuilt evidence sits next to every claim, so a reviewer always sees the actual source.
- **Privacy:** transcripts and results are stored in Supabase for the history feature; the
  demo RLS policy is open for easy review and must be tightened for production. Audio is
  written to a temp file only for the duration of transcription, then deleted. Sensitive
  data in a transcript is itself flagged for human review.
- **Mock mode is honest:** for transcripts it hasn't seen it says so rather than inventing
  extraction.

## Limitations & future improvements

- Transcription confidence isn't yet used to route low-confidence speech to review.
- User-defined domains via the UI (today they're edited in `agent.py`).
- A dedicated reviewer screen with per-item accept/override actions.
- Auth + tenant isolation and tighter RLS before any real data.
