"""
Call Intelligence Agent — core workflow.

This is a faithful port of app.ipynb into an importable module, plus:
  - an LLM-optional MOCK mode (runs with no OpenAI key so a reviewer can demo it), and
  - a streaming runner (`run_stream`) that emits a trace event per workflow node
    so the UI can show the agent's processing in action.

The workflow (unchanged from the notebook / architecture doc):

    segment_transcript -> classify_domain -> [extract_items || review_compliance]
                       -> verify_grounding -> assemble_output

Everything that must be reliable (line numbering, citation checking, evidence
rebuilding) is plain deterministic Python. The model is used only for reading and
judging language.
"""
from __future__ import annotations

import os
import time
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, create_model

# .env lives at the repo root (one level up from backend/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

MODEL = os.getenv("MODEL", "gpt-4.1")

# LLM is optional. If no key, we fall back to deterministic MOCK mode so the app
# is fully runnable with "no required paid/secret API key".
_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
USE_LLM = bool(_OPENAI_KEY) and os.getenv("FORCE_MOCK", "").lower() not in ("1", "true", "yes")

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI

        os.environ["OPENAI_API_KEY"] = _OPENAI_KEY
        _llm = ChatOpenAI(model=MODEL, temperature=0)
    return _llm


# --------------------------------------------------------------------------- #
# Schemas (from the notebook)                                                  #
# --------------------------------------------------------------------------- #
class Decision(BaseModel):
    decision: str = Field(description="the decision that was made or agreed")
    source_ids: List[int] = Field(description="transcript line ids supporting this")
    evidence: str = ""
    citation_verified: bool = False


class ActionItem(BaseModel):
    task: str = Field(description="the task to be done")
    owner: Optional[str] = Field(default=None, description="person responsible; null if not clearly stated")
    start: Optional[str] = Field(default=None, description="start date YYYY-MM-DD or null")
    due: Optional[str] = Field(default=None, description="due date YYYY-MM-DD or null")
    source_ids: List[int] = Field(description="transcript line ids supporting this")
    evidence: str = ""
    citation_verified: bool = False


class Blocker(BaseModel):
    blocker: str = Field(description="what is blocking progress")
    source_ids: List[int] = Field(description="transcript line ids supporting this")
    evidence: str = ""
    citation_verified: bool = False


class ExtractionResult(BaseModel):
    """What the extraction agent returns."""
    tag: str = Field(description="one short line hinting what the call was about")
    summary: str = Field(description="3-6 sentence neutral summary")
    recommended_next_steps: List[str] = Field(default_factory=list)
    decisions: List[Decision] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    blockers: List[Blocker] = Field(default_factory=list)


class ComplianceObservation(BaseModel):
    note: str = Field(description="what the issue is and why it matters")
    status: Literal["Red", "Yellow", "Green"] = Field(
        description="Red=likely violation/serious risk; Yellow=coaching/soft risk; Green=required step followed"
    )
    source_ids: List[int]
    evidence: str = ""


class ReviewItem(BaseModel):
    item: str = Field(description="the specific thing a human should look at")
    reason: str = Field(description="why it needs a human")
    category: str = Field(description="a short free-form label for the kind of issue")
    source_ids: List[int]
    evidence: str = ""


class ReviewResult(BaseModel):
    compliance_observations: List[ComplianceObservation] = Field(default_factory=list)
    items_needing_human_review: List[ReviewItem] = Field(default_factory=list)


class MeetingIntelligence(BaseModel):
    tag: str = ""
    domain: str = ""
    domain_agent: str = ""
    anchor_date: str = ""
    summary: str = ""
    recommended_next_steps: List[str] = Field(default_factory=list)
    decisions: List[Decision] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    blockers: List[Blocker] = Field(default_factory=list)
    compliance_observations: List[ComplianceObservation] = Field(default_factory=list)
    items_needing_human_review: List[ReviewItem] = Field(default_factory=list)
    segment_count: int = 0
    domain_rationale: str = ""
    mock_mode: bool = False


# --------------------------------------------------------------------------- #
# Ingest / segmentation (plain code — the grounding foundation)               #
# --------------------------------------------------------------------------- #
def ingest(raw: str, meeting_date: date | str | None = None):
    if meeting_date is None or meeting_date == "":
        anchor = date.today()
    elif isinstance(meeting_date, str):
        anchor = date.fromisoformat(meeting_date)
    else:
        anchor = meeting_date

    segments, idx = [], 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        idx += 1
        segments.append({"id": idx, "text": stripped})

    lookup = {s["id"]: s for s in segments}
    meta = {
        "anchor_date": anchor.isoformat(),
        "anchor_weekday": anchor.strftime("%A"),
        "anchor_source": "provided" if meeting_date else "today (default)",
        "segment_count": len(segments),
    }
    return segments, lookup, meta


def numbered(segments) -> str:
    return "\n".join(f"{s['id']}: {s['text']}" for s in segments)


# --------------------------------------------------------------------------- #
# Domain registry (swappable context)                                         #
#                                                                             #
# Built-in domains ship in code; custom domains are stored in Supabase and    #
# merged in at run time, so the agent can refer to whichever domains exist    #
# (add / update / delete via the API) with no code change.                    #
# --------------------------------------------------------------------------- #
BUILTIN_DOMAINS = {
    "debt_collection": {
        "agent": "Collections Compliance Specialist",
        "description": "A debt collector/agency contacting a consumer to collect or resolve an outstanding balance (credit card, auto, medical, etc.).",
        "context": """US debt-collection call (FDCPA-adjacent). Watch for:
- Missing Tape Disclosure (call is being recorded) and mini-Miranda statement before sharing any debt related information ("this is an attempt to collect a debt and any information obtained will be used for that purpose").
- Identity verification (Full Name) BEFORE sharing account details.
- Check if there any third party debt disclosure (sharing someone's debt with someone else is prohibited).
- RED: third party disclosure, account details before verification; missing tape disclosure and mini-Miranda; threats or
  misleading statements; full SSN spoken aloud, FDCPA violations.
- YELLOW: settlement/waiver promised above the settlement authority;
- Keep in mind: a promise-to-pay is an action item (owner = agent needs to follow up on agreed dates); any
  settlement above 50 percent discount/waiver needs supervisor approval -> human judgment; any post dated payments or part payments scheduled for future dates are action items (owner = agent needs to follow up on agreed dates);
  Mark account as 'paid in full' or 'settled' if full balance or settlement amount is paid then and there and close these accounts to stop further collection activity. If the account is disputed, mark as 'disputed' and forward to the dispute team for further investigation.""",
    },
    "sales": {
        "agent": "Sales Deal-Desk Reviewer",
        "description": "A sales rep engaging a prospect or existing customer to qualify, demo, price, negotiate, or close — including renewals and upsells.",
        "context": """B2B/B2C sales call (discovery / demo / negotiation / closing). Watch for:
- Discovery captured: prospect's pain, current tooling, team size/seats, timeline, and budget authority (who signs off).
- Pricing stated clearly: list price vs quoted price, discount %, contract term, and whether it's verbal or in writing.
- RED: pricing/discount/term commitments made BEYOND the rep's discount authority without manager approval; guarantees about unshipped features or delivery dates ("it'll definitely ship next month"); claims about competitors or other customers' data that can't be substantiated; verbal side-agreements not reflected in the contract.
- YELLOW: discount discussed but final number left fuzzy; next step agreed with no owner or date; single-threaded deal (only one contact, no economic buyer engaged); ROI/pricing quoted from memory rather than the approved price book.
- Keep in mind: "we'll go with the Pro plan" is a DECISION; sending the proposal/order form/DPA and looping in procurement or legal are ACTION ITEMS (owner = rep unless stated otherwise) — resolve their dates. A discount above the rep's authority threshold needs manager/deal-desk approval -> human judgment. Blockers are usually procurement sign-off, security/legal review, or budget approval; capture them as blockers, not decisions. Track the agreed next meeting as an action item with a date.""",
    },
    "customer_support": {
        "agent": "Support QA Reviewer",
        "description": "An existing customer contacting support about a problem, request, billing issue, or escalation.",
        "context": """Customer support / service call (issue -> troubleshoot -> resolution or escalation). Watch for:
- Verification appropriate to the action: identity/account ownership confirmed before account changes, refunds, or sharing account data.
- Issue and resolution captured: what broke, what was done, and what was promised (refund, replacement, credit, callback, timeline/SLA).
- RED: sensitive data (full card number, SSN, DOB, passwords, OTPs) read aloud or asked for insecurely; account changes/refunds processed without verifying ownership; commitments (refund amount, "fixed by tomorrow", SLA) made without authority or system confirmation; PII shared with a third party / wrong account.
- YELLOW: consent to record unclear; resolution promised but system/tool status uncertain ("I think our refund system is back up"); no ticket/case number created; customer dissatisfied and churn/complaint risk not flagged; workaround given without a real fix.
- Keep in mind: a promised refund/credit, a callback, opening or escalating a ticket, and a follow-up are all ACTION ITEMS (owner = agent) — resolve their dates. Note explicitly when the agent LACKS authority to do what the customer wants -> escalation / human judgment. A confirmed fix or approved refund is a DECISION; an unresolved dependency (outage, waiting on another team) is a BLOCKER. Capture the case/ticket number if one is mentioned.""",
    },
}


import re as _re

RESERVED_KEYS = {"general_meeting"}
_domain_cache = {"data": None, "ts": 0.0}


def _load_custom_domains() -> dict:
    """Custom domains from Supabase, cached briefly to avoid a read per node."""
    now = time.time()
    if _domain_cache["data"] is not None and (now - _domain_cache["ts"]) < 3:
        return _domain_cache["data"]
    out = {}
    try:
        import db

        for row in db.list_domains():
            key = row.get("key")
            if key and key not in BUILTIN_DOMAINS and key not in RESERVED_KEYS:
                out[key] = {"agent": row.get("agent", ""), "description": row.get("description", ""),
                            "context": row.get("context", ""), "custom": True}
    except Exception as e:  # DB optional — never break a run over the registry
        print(f"[agent] custom domain load failed: {e}")
    _domain_cache.update(data=out, ts=now)
    return out


def get_domains() -> dict:
    """Built-in + custom domains, merged (custom cannot override a built-in key)."""
    merged = {k: {**v, "custom": False} for k, v in BUILTIN_DOMAINS.items()}
    merged.update(_load_custom_domains())
    return merged


def invalidate_domain_cache():
    _domain_cache.update(data=None, ts=0.0)


def upsert_domain(key: str, agent: str, description: str, context: str) -> str | None:
    key = (key or "").strip().lower()
    key = _re.sub(r"[^a-z0-9_]+", "_", key).strip("_")
    if not key or key in BUILTIN_DOMAINS or key in RESERVED_KEYS:
        return None
    if not (agent.strip() and description.strip()):
        return None
    import db

    if not db.upsert_domain(key, agent.strip(), description.strip(), context.strip()):
        return None
    invalidate_domain_cache()
    return key


def delete_domain(key: str) -> bool:
    if key in BUILTIN_DOMAINS or key in RESERVED_KEYS:
        return False
    import db

    ok = db.delete_domain(key)
    invalidate_domain_cache()
    return ok


def get_domain_context(domain: str) -> str:
    d = get_domains().get(domain)
    return d["context"] if d else ""


def get_domain_agent(domain: str) -> str:
    d = get_domains().get(domain)
    return d["agent"] if d else "General Meeting Facilitator"


def _domain_menu() -> str:
    lines = [f"- {name}: {d['description']}" for name, d in get_domains().items()]
    lines.append("- general_meeting: none of the above / internal team meeting or unclear.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Prompts (from the notebook)                                                  #
# --------------------------------------------------------------------------- #
ROUTER_SYSTEM = """You are a call/meeting classifier.

You will be given a numbered transcript and a list of candidate domains, each with a short description. Read the transcript and decide which single domain it best fits.

Rules:
- Choose exactly one domain from the provided list.
- Base the decision on what the conversation actually is (who the speakers are and what they're doing), not on isolated keywords.
- If the transcript does not clearly fit any provided domain, return "general_meeting".
- Give a one-sentence rationale."""

EXTRACTION_SYSTEM = """You extract structured intelligence from a numbered meeting/call transcript. You are precise and conservative: you never invent facts, owners, or dates.

TRANSCRIPT FORMAT
Each line is "<id>: <text>", where <id> is the integer line number. That id is the ONLY way to cite evidence.

GROUNDING (hard rules)
- Every decision, action item, and blocker MUST include source_ids: the integer line id(s) that directly support it. Cite the minimum lines needed.
- Only cite ids that exist in the transcript. Never guess an id.
- If something is implied but not actually stated (e.g. an owner is never named), leave that field null. Do NOT guess — a human-review step exists for gaps.

DATES (use temporal reasoning)
- You are given ANCHOR_DATE (the meeting date) and its weekday. Resolve every relative or fuzzy date expression against that anchor and output a concrete calendar date in YYYY-MM-DD.
  Examples given anchor Wednesday 2026-07-01: "this week Wednesday" -> 2026-07-01; "Friday" -> 2026-07-03; "end of next week" -> 2026-07-10; "the 15th of next month" -> 2026-08-15; "tomorrow" -> 2026-07-02; "in two weeks" -> 2026-07-15.
- For action items, set `start` and/or `due` only when a time is stated or clearly implied; otherwise null. If only one date is mentioned, treat it as `due`. Do not output a date you could not derive from the transcript.
- If a date phrase is too vague to resolve to a single day (e.g. "sometime soon", "in the coming weeks"), leave the date null (a human will follow up).

WHAT TO EXTRACT
- tag: one short line hinting what the call was about.
- summary: 3-6 neutral sentences.
- recommended_next_steps: short actionable follow-ups.
- decisions: things actually agreed/decided (not mere discussion).
- action_items: task + owner (or null) + start/due (or null) + source_ids.
- blockers: things stopping progress (dependencies, waiting-on, unresolved issues).

Distinguish a DECISION ("we'll go with X") from an ACTION ITEM ("I'll do X by Friday") from a BLOCKER ("we can't do X until Y"). Use the domain context, if provided, only as guidance on what matters in this kind of call — do not force items that aren't there.

Return the structured object only."""

COMPLIANCE_SYSTEM = """You are a QA & compliance reviewer for a meeting/call transcript. Read the numbered transcript and surface (a) compliance observations and (b) anything a human should review. Use the DOMAIN CONTEXT, when provided, as your rulebook; otherwise use general good judgment.

GROUNDING (hard rules)
- Every observation and review item MUST cite source_ids (integer line numbers) that support it. Only cite ids that actually exist. Do not speculate beyond what the lines show.

COMPLIANCE OBSERVATIONS
- Red: a likely violation or serious risk (per the domain rules if given, else general standards).
- Yellow: a coaching issue or soft risk worth a human glance.
- Green (optional): note where a required step was correctly followed.

ITEMS NEEDING HUMAN REVIEW
Flag anything that is uncertain, risky, or beyond what an AI should decide on its own. This is open-ended. Examples of the KINDS of things to flag (not exhaustive):
- an action item whose deadline is vague, or whose owner/scope/details are missing or unclear;
- a customer/consumer giving unclear or ambiguous consent;
- a possible compliance issue;
- a decision that requires human judgment;
- something the AI does not have the authority or permission to decide or commit to;
- anything unclear or under-specified from the conversation or context;
- sensitive or risky information in the transcript (e.g. personal identifiers, financial data);
- any other situation where a reasonable reviewer would want a human to look before acting.

Choose a short, descriptive category label for each item yourself (free text).

Be conservative and specific: cite the lines, explain the concern in one or two sentences, and don't invent problems to fill space. If the call is genuinely clean, return empty lists. Return the structured object only."""


# --------------------------------------------------------------------------- #
# LLM node functions (with mock fallbacks)                                     #
# --------------------------------------------------------------------------- #
def classify_domain(segments):
    allowed = tuple(get_domains().keys()) + ("general_meeting",)
    if not USE_LLM:
        from mock_engine import mock_classify

        return mock_classify(segments, allowed)

    Classification = create_model(
        "Classification",
        domain=(str, Field(description=f"one of: {', '.join(allowed)}")),
        rationale=(str, Field(description="one short sentence")),
    )
    router = get_llm().with_structured_output(Classification)
    result = router.invoke([
        ("system", ROUTER_SYSTEM),
        ("human", f"CANDIDATE DOMAINS:\n{_domain_menu()}\n\nTRANSCRIPT:\n{numbered(segments)}"),
    ])
    if result.domain not in allowed:
        result.domain = "general_meeting"
    return result


def extract(segments, domain_context: str, meta) -> ExtractionResult:
    if not USE_LLM:
        from mock_engine import mock_extract

        return mock_extract(segments, meta)

    extractor = get_llm().with_structured_output(ExtractionResult)
    ctx = domain_context.strip() or "(none — general meeting, no special domain rules)"
    user = (
        f"ANCHOR_DATE: {meta['anchor_date']} ({meta['anchor_weekday']})\n"
        f"Resolve all relative dates against this anchor.\n\n"
        f"DOMAIN CONTEXT (reference only, do not quote as transcript):\n{ctx}\n\n"
        f"NUMBERED TRANSCRIPT:\n{numbered(segments)}"
    )
    return extractor.invoke([("system", EXTRACTION_SYSTEM), ("human", user)])


def review(segments, domain_context: str) -> ReviewResult:
    if not USE_LLM:
        from mock_engine import mock_review

        return mock_review(segments)

    reviewer = get_llm().with_structured_output(ReviewResult)
    ctx = domain_context.strip() or "(none — general meeting; use general judgment only)"
    user = (
        f"DOMAIN CONTEXT (your rulebook, may be empty):\n{ctx}\n\n"
        f"NUMBERED TRANSCRIPT:\n{numbered(segments)}"
    )
    return reviewer.invoke([("system", COMPLIANCE_SYSTEM), ("human", user)])


# --------------------------------------------------------------------------- #
# Grounding (deterministic anti-hallucination gate)                           #
# --------------------------------------------------------------------------- #
def render_evidence(source_ids, lookup) -> str:
    parts = []
    for sid in source_ids:
        seg = lookup.get(sid)
        if seg is not None:
            parts.append(f"{sid}: {seg['text']}")
    return "  |  ".join(parts)


def ground_item(item, lookup):
    ids = item.source_ids
    bad = [i for i in ids if i not in lookup]
    valid = [i for i in ids if i in lookup]
    item.evidence = render_evidence(valid, lookup)
    if hasattr(item, "citation_verified"):
        item.citation_verified = not bad and bool(valid)
    return bad, valid


def ground_all(extraction: ExtractionResult, rev: ReviewResult, lookup):
    review_items = list(rev.items_needing_human_review)
    buckets = [
        ("decision", extraction.decisions),
        ("action item", extraction.action_items),
        ("blocker", extraction.blockers),
        ("compliance observation", rev.compliance_observations),
    ]
    for kind, items in buckets:
        for it in items:
            bad, valid = ground_item(it, lookup)
            if bad:
                label = (
                    getattr(it, "decision", None) or getattr(it, "task", None)
                    or getattr(it, "blocker", None) or getattr(it, "note", None) or kind
                )
                review_items.append(ReviewItem(
                    item=f"{kind}: {label}",
                    reason=f"Cited transcript line(s) {bad} do not exist — citation could not be grounded.",
                    category="unverified_citation",
                    source_ids=valid,
                    evidence=render_evidence(valid, lookup),
                ))
    for r in review_items:
        ground_item(r, lookup)
    return review_items


# --------------------------------------------------------------------------- #
# LangGraph pipeline (kept for fidelity / tests)                              #
# --------------------------------------------------------------------------- #
def build_graph():
    from typing import TypedDict
    from langgraph.graph import StateGraph, START, END

    class State(TypedDict, total=False):
        raw_transcript: str
        meeting_date: Optional[str]
        segments: List[Dict[str, Any]]
        lookup: Dict[int, Dict[str, Any]]
        meta: Dict[str, Any]
        domain: str
        domain_rationale: str
        domain_context: str
        extraction: ExtractionResult
        review: ReviewResult
        review_items: List[ReviewItem]
        final: MeetingIntelligence

    def n_ingest(s):
        segments, lookup, meta = ingest(s["raw_transcript"], s.get("meeting_date"))
        return {"segments": segments, "lookup": lookup, "meta": meta}

    def n_route(s):
        c = classify_domain(s["segments"])
        return {"domain": c.domain, "domain_rationale": c.rationale,
                "domain_context": get_domain_context(c.domain)}

    def n_extract(s):
        return {"extraction": extract(s["segments"], s["domain_context"], s["meta"])}

    def n_review(s):
        return {"review": review(s["segments"], s["domain_context"])}

    def n_ground(s):
        return {"review_items": ground_all(s["extraction"], s["review"], s["lookup"])}

    def n_assemble(s):
        ex, rev = s["extraction"], s["review"]
        final = MeetingIntelligence(
            tag=ex.tag, domain=s["domain"], domain_agent=get_domain_agent(s["domain"]),
            anchor_date=s["meta"]["anchor_date"], summary=ex.summary,
            recommended_next_steps=ex.recommended_next_steps,
            decisions=ex.decisions, action_items=ex.action_items, blockers=ex.blockers,
            compliance_observations=rev.compliance_observations,
            items_needing_human_review=s["review_items"],
            segment_count=s["meta"]["segment_count"],
            domain_rationale=s["domain_rationale"], mock_mode=not USE_LLM,
        )
        return {"final": final}

    g = StateGraph(State)
    g.add_node("segment_transcript", n_ingest)
    g.add_node("classify_domain", n_route)
    g.add_node("extract_items", n_extract)
    g.add_node("review_compliance", n_review)
    g.add_node("verify_grounding", n_ground)
    g.add_node("assemble_output", n_assemble)
    g.add_edge(START, "segment_transcript")
    g.add_edge("segment_transcript", "classify_domain")
    g.add_edge("classify_domain", "extract_items")
    g.add_edge("classify_domain", "review_compliance")
    g.add_edge("extract_items", "verify_grounding")
    g.add_edge("review_compliance", "verify_grounding")
    g.add_edge("verify_grounding", "assemble_output")
    g.add_edge("assemble_output", END)
    return g.compile()


def run_pipeline(transcript: str, meeting_date: str | None = None) -> MeetingIntelligence:
    app = build_graph()
    out = app.invoke({"raw_transcript": transcript, "meeting_date": meeting_date})
    return out["final"]


# --------------------------------------------------------------------------- #
# Streaming runner — emits a trace event per node for observability.          #
# Runs the same node logic as the graph, in sequence, yielding progress.      #
# --------------------------------------------------------------------------- #
def run_stream(transcript: str, meeting_date: str | None = None):
    """Generator yielding trace dicts: {node, title, status, detail, elapsed_ms, ...}."""
    t0 = time.time()

    def ev(node, title, status, detail=None, **extra):
        e = {"node": node, "title": title, "status": status,
             "elapsed_ms": int((time.time() - t0) * 1000)}
        if detail is not None:
            e["detail"] = detail
        e.update(extra)
        return e

    yield ev("start", "Workflow started", "info",
             detail=f"Mode: {'LLM (' + MODEL + ')' if USE_LLM else 'MOCK (deterministic, no API key)'}",
             mock_mode=not USE_LLM)

    # 1. segment_transcript
    yield ev("segment_transcript", "Segmenting transcript", "running",
             detail="Numbering every line — this is the anchor for all citations.")
    segments, lookup, meta = ingest(transcript, meeting_date)
    yield ev("segment_transcript", "Segmented transcript", "done",
             detail=f"{meta['segment_count']} lines. Anchor date {meta['anchor_date']} "
                    f"({meta['anchor_weekday']}, {meta['anchor_source']}).",
             segments=segments, meta=meta)

    # 2. classify_domain
    yield ev("classify_domain", "Routing to a domain agent", "running",
             detail="Reading the call to decide its type and load the matching rulebook.")
    c = classify_domain(segments)
    ctx = get_domain_context(c.domain)
    agent_name = get_domain_agent(c.domain)
    yield ev("classify_domain", f"Domain: {c.domain}", "done",
             detail=f"{agent_name} joined. {c.rationale}",
             domain=c.domain, domain_agent=agent_name, rationale=c.rationale)

    # 3. extract_items (parallel branch A)
    yield ev("extract_items", "Extraction agent working", "running",
             detail="Pulling summary, decisions, action items, blockers — each cited to line ids.")
    extraction = extract(segments, ctx, meta)
    yield ev("extract_items", "Extraction complete", "done",
             detail=f"{len(extraction.decisions)} decisions, {len(extraction.action_items)} "
                    f"action items, {len(extraction.blockers)} blockers.",
             extraction=extraction.model_dump())

    # 4. review_compliance (parallel branch B)
    yield ev("review_compliance", f"{agent_name} reviewing", "running",
             detail="Reading the same call critically against the domain rulebook.")
    rev = review(segments, ctx)
    yield ev("review_compliance", "Compliance review complete", "done",
             detail=f"{len(rev.compliance_observations)} observations, "
                    f"{len(rev.items_needing_human_review)} pre-grounding review items.",
             review=rev.model_dump())

    # 5. verify_grounding
    yield ev("verify_grounding", "Verifying grounding", "running",
             detail="Deterministic gate: checking every cited line exists and rebuilding evidence from source.")
    review_items = ground_all(extraction, rev, lookup)
    bogus = sum(1 for r in review_items if r.category == "unverified_citation")
    yield ev("verify_grounding", "Grounding verified", "done",
             detail=f"Evidence rebuilt from transcript. {bogus} fabricated citation(s) caught and escalated."
                    if bogus else "Evidence rebuilt from transcript for every item. All citations valid.")

    # 6. assemble_output
    final = MeetingIntelligence(
        tag=extraction.tag, domain=c.domain, domain_agent=agent_name,
        anchor_date=meta["anchor_date"], summary=extraction.summary,
        recommended_next_steps=extraction.recommended_next_steps,
        decisions=extraction.decisions, action_items=extraction.action_items,
        blockers=extraction.blockers, compliance_observations=rev.compliance_observations,
        items_needing_human_review=review_items, segment_count=meta["segment_count"],
        domain_rationale=c.rationale, mock_mode=not USE_LLM,
    )
    yield ev("assemble_output", "Assembled structured notes", "done",
             detail=f"{len(review_items)} item(s) flagged for human review.")
    yield ev("result", "Result ready", "result", segments=segments, result=final.model_dump())


# --------------------------------------------------------------------------- #
# AssemblyAI transcription (optional audio path)                              #
# --------------------------------------------------------------------------- #
def transcribe_audio(file_path: str) -> dict:
    """Audio file -> diarized transcript. Returns {'transcript': str, 'utterances': list}."""
    import assemblyai as aai

    key = os.getenv("ASSEMBLYAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set — cannot transcribe audio in this environment.")
    aai.settings.api_key = key

    # SDK 0.35.x + current API: don't set speech_model (the param is deprecated and the
    # API now rejects it); the default model is Universal. Diarization via speaker_labels.
    config = aai.TranscriptionConfig(
        speaker_labels=True,
        punctuate=True,
        format_text=True,
        language_code="en_us",
    )

    transcript = aai.Transcriber().transcribe(file_path, config=config)
    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI failed: {transcript.error}")

    lines, utterances = [], []
    for u in (transcript.utterances or []):
        spk, txt = f"Speaker {u.speaker}", u.text
        utterances.append({"speaker": spk, "text": txt})
        lines.append(f"{spk}: {txt}")
    if not lines:  # very short / single-speaker / silent audio
        lines = [transcript.text or ""]
    return {"transcript": "\n".join(lines), "utterances": utterances}
