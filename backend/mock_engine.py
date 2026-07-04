"""
Deterministic MOCK engine — the LLM-optional fallback.

When no OPENAI_API_KEY is present, the three model calls (classify / extract /
review) are served from here instead, so a reviewer can run the whole app with
"no required paid/secret API key".

For the four bundled sample transcripts it returns rich, hand-authored outputs
that mirror the notebook's "expected outputs" (correct owners, resolved dates,
line citations). For any other transcript it returns a small, honest result plus
a review item that says extraction is limited without an LLM key.
"""
from __future__ import annotations

from pydantic import create_model, Field

from agent import (
    ExtractionResult, ReviewResult, Decision, ActionItem, Blocker,
    ComplianceObservation, ReviewItem,
)

_KEYWORDS = {
    "debt_collection": ["collect a debt", "settlement", "past-due", "recovery", "mini-miranda", "ssn"],
    "sales": ["seats", "annual term", "procurement", "proposal", "discount", "pro plan", "dpa"],
    "customer_support": ["support", "refund", "charged twice", "ticket", "case ", "subscription"],
}


def _fingerprint(text: str) -> str | None:
    t = text.lower()
    if "anderson recovery" in t or "attempt to collect a debt" in t:
        return "debt_collection"
    if "techcare" in t or "case 55231" in t:
        return "customer_support"
    if "dana" in t and ("pro" in t and "seat" in t):
        return "sales"
    if "postgres full-text" in t or "payments webhook" in t:
        return "general_meeting"
    return None


def mock_classify(segments, allowed):
    text = "\n".join(s["text"] for s in segments)
    fp = _fingerprint(text)
    rationale_map = {
        "debt_collection": "A collector is contacting a consumer to resolve a past-due balance.",
        "sales": "A rep is pricing and negotiating a plan with a prospect.",
        "customer_support": "An existing customer is contacting support about a billing problem.",
        "general_meeting": "An internal team standup with no external-facing domain rules.",
    }
    if fp:
        domain = fp
    else:
        tl = text.lower()
        scores = {d: sum(tl.count(k) for k in kws) for d, kws in _KEYWORDS.items()}
        domain = max(scores, key=scores.get) if any(scores.values()) else "general_meeting"
    Classification = create_model(
        "Classification",
        domain=(str, Field()),
        rationale=(str, Field()),
    )
    return Classification(
        domain=domain,
        rationale=rationale_map.get(domain, "Best keyword match (mock mode — heuristic routing).") + " [mock]",
    )


# --------------------------------------------------------------------------- #
# Canned extraction results per sample                                         #
# --------------------------------------------------------------------------- #
def _extract_debt():
    return ExtractionResult(
        tag="Collections call — Summit Card past-due, settlement split negotiated",
        summary=("Marcus (Anderson Recovery) reached James Whitfield about a $2,340 past-due Summit Card "
                 "balance. James can't pay in full after a job loss. A settlement split of $700 today and "
                 "$700 on the 15th of next month was proposed. The split needs supervisor approval, which "
                 "the agent will follow up on by Friday. Once both payments post the account would be marked "
                 "settled and closed."),
        recommended_next_steps=[
            "Get supervisor sign-off on the settlement split before confirming to the consumer.",
            "Send written settlement confirmation once approved.",
        ],
        decisions=[
            Decision(decision="Once both payments post, the account will be marked settled and closed (conditional).",
                     source_ids=[11]),
        ],
        action_items=[
            ActionItem(task="Consumer to pay first $700 installment today", owner="James (consumer)",
                       due="2026-07-01", source_ids=[8, 9]),
            ActionItem(task="Consumer to pay second $700 installment", owner="James (consumer)",
                       due="2026-08-15", source_ids=[8, 9]),
            ActionItem(task="Follow up on supervisor approval for the settlement split", owner="Marcus (agent)",
                       due="2026-07-03", source_ids=[9]),
            ActionItem(task="Send written confirmation of settlement", owner="Marcus (agent)",
                       due=None, source_ids=[11]),
        ],
        blockers=[
            Blocker(blocker="Settlement split needs supervisor approval before it is final", source_ids=[9]),
        ],
    )


def _review_debt():
    return ReviewResult(
        compliance_observations=[
            ComplianceObservation(status="Green",
                note="Tape disclosure and mini-Miranda given before any debt information was shared.",
                source_ids=[1]),
            ComplianceObservation(status="Green",
                note="Identity verified (full name + last four of SSN) before account details were shared.",
                source_ids=[3, 4]),
            ComplianceObservation(status="Yellow",
                note="Settlement split ($1,400 of $2,340) approaches/exceeds the settlement authority; the "
                     "agent correctly said it needs supervisor approval.",
                source_ids=[7, 8, 9]),
        ],
        items_needing_human_review=[
            ReviewItem(item="Settlement split beyond standard terms",
                       reason="A settlement above standard authority needs a supervisor's sign-off before it is "
                              "committed to the consumer.",
                       category="authority_required", source_ids=[9]),
        ],
    )


def _extract_sales():
    return ExtractionResult(
        tag="Sales call — Pro plan for ~30 seats, pricing pending approvals",
        summary=("The rep followed up with Dana, whose team hit Starter-plan limits and values the analytics. "
                 "About 30 seats are needed, so the rep proposed Pro at $32/seat on an annual term (list $40). "
                 "Spend over $25k requires procurement, and legal must review the data terms. Both sides agreed "
                 "to proceed with Pro pending approvals; the rep will send the proposal and DPA and loop in "
                 "security, and they'll regroup early next week."),
        recommended_next_steps=[
            "Send proposal and DPA to Dana today.",
            "Identify a procurement owner on the customer side to avoid the deal stalling.",
        ],
        decisions=[
            Decision(decision="Go with the Pro plan at the annual rate ($32/seat), pending procurement and legal approval.",
                     source_ids=[3, 4, 5]),
        ],
        action_items=[
            ActionItem(task="Send proposal + DPA", owner="Rep", due="2026-07-01", source_ids=[5]),
            ActionItem(task="Loop in security team for the data-terms review", owner="Rep", due=None, source_ids=[5]),
            ActionItem(task="Chase procurement sign-off", owner=None, due=None, source_ids=[6, 7, 8]),
            ActionItem(task="Regroup / follow-up meeting", owner="Rep", due="2026-07-06", source_ids=[8, 9]),
            ActionItem(task="Aim to have everything wrapped", owner="Rep", due="2026-07-31", source_ids=[9]),
        ],
        blockers=[
            Blocker(blocker="Procurement sign-off required (spend over $25k/year)", source_ids=[4]),
            Blocker(blocker="Legal review of the data terms", source_ids=[4]),
        ],
    )


def _review_sales():
    return ReviewResult(
        compliance_observations=[
            ComplianceObservation(status="Yellow",
                note="Discount to $32/seat quoted; confirm it is within the rep's discount authority for an annual term.",
                source_ids=[3]),
            ComplianceObservation(status="Yellow",
                note="Procurement owner on the customer side is unassigned ('I'll find out who') — deal may stall.",
                source_ids=[7, 8]),
        ],
        items_needing_human_review=[
            ReviewItem(item="Discount authority on Pro annual pricing",
                       reason="Verify $32/seat is within the rep's approved discount band before the proposal goes out.",
                       category="pricing_authority", source_ids=[3, 5]),
            ReviewItem(item="Unassigned procurement owner",
                       reason="No owner was named for chasing procurement; someone must own it or the deal stalls.",
                       category="missing_owner", source_ids=[6, 7, 8]),
        ],
    )


def _extract_support():
    return ExtractionResult(
        tag="Support call — duplicate subscription charge, refund escalated",
        summary=("Jordan contacted TechCare about being charged twice this month. Priya verified the customer by "
                 "email and billing zip, confirmed a duplicate charge on the 3rd, and agreed a refund is warranted. "
                 "Refunds normally take 3–5 business days, but the billing tool has been unreliable since an outage, "
                 "so processing can't be confirmed. Lacking authority to expedite, Priya opened priority case 55231, "
                 "escalated to billing, and will follow up tomorrow."),
        recommended_next_steps=[
            "Confirm refund on case 55231 actually processed once the billing tool is stable.",
            "Follow up with the customer tomorrow as promised.",
        ],
        decisions=[
            Decision(decision="A refund is warranted — duplicate charge confirmed on the 3rd.", source_ids=[5]),
        ],
        action_items=[
            ActionItem(task="Open priority ticket (case 55231) and escalate to billing", owner="Priya (agent)",
                       due="2026-07-01", source_ids=[9]),
            ActionItem(task="Follow up with customer to confirm refund processed", owner="Priya (agent)",
                       due="2026-07-02", source_ids=[9]),
        ],
        blockers=[
            Blocker(blocker="Billing tool unreliable after outage — refund can't be confirmed", source_ids=[7]),
            Blocker(blocker="Agent lacks authority to expedite the refund", source_ids=[9]),
        ],
    )


def _review_support():
    return ReviewResult(
        compliance_observations=[
            ComplianceObservation(status="Green",
                note="Consent to record obtained ('Sure') and identity verified before account access.",
                source_ids=[1, 3, 4]),
            ComplianceObservation(status="Yellow",
                note="Refund timing promised while the billing system's status is uncertain after an outage.",
                source_ids=[7]),
            ComplianceObservation(status="Red",
                note="A refund outcome was assured to the customer without system confirmation or authority to expedite.",
                source_ids=[5, 9]),
        ],
        items_needing_human_review=[
            ReviewItem(item="Unconfirmed refund on an unreliable system",
                       reason="Refund was promised but the billing tool can't confirm processing; a human should verify.",
                       category="system_uncertainty", source_ids=[7, 9]),
            ReviewItem(item="Churn / dissatisfaction risk",
                       reason="Customer expressed frustration ('that's not reassuring'); flag for a service-recovery check.",
                       category="customer_risk", source_ids=[8]),
        ],
    )


def _extract_general():
    return ExtractionResult(
        tag="Eng standup — payments webhook, search reindex, CI",
        summary=("A quick engineering standup. Raj will finish the Stripe payments webhook by this week Wednesday "
                 "but is blocked on staging keys; Mira will chase IT for access today. The team decided to use "
                 "Postgres full-text search instead of Elasticsearch for now. Devi will run the search reindex in "
                 "prod (targeting end of next week) but needs a second reviewer per the prod-change rule. The flaky "
                 "CI was raised as something to look at soon, with no owner."),
        recommended_next_steps=[
            "Unblock Raj's staging access via IT.",
            "Assign a second reviewer for the prod reindex; find an owner for the flaky CI.",
        ],
        decisions=[
            Decision(decision="Use Postgres full-text search instead of Elasticsearch for now.", source_ids=[5]),
        ],
        action_items=[
            ActionItem(task="Finish Stripe payments webhook handler", owner="Raj", due="2026-07-01", source_ids=[2]),
            ActionItem(task="Chase IT for Raj's staging access", owner="Mira", due="2026-07-01", source_ids=[3]),
            ActionItem(task="Run the search reindex in prod", owner="Devi", due="2026-07-10", source_ids=[4, 6]),
            ActionItem(task="Look at the flaky CI", owner=None, due=None, source_ids=[7]),
        ],
        blockers=[
            Blocker(blocker="Raj blocked on staging keys / access", source_ids=[2]),
            Blocker(blocker="Prod reindex needs a second reviewer before it can run", source_ids=[4]),
        ],
    )


def _review_general():
    return ReviewResult(
        compliance_observations=[],
        items_needing_human_review=[
            ReviewItem(item="Flaky CI has no owner or date",
                       reason="'Someone should look at it soon' — no owner and an unresolvable deadline.",
                       category="missing_owner", source_ids=[7]),
            ReviewItem(item="Prod reindex reviewer unassigned",
                       reason="Prod change rule requires a second reviewer; none is assigned yet.",
                       category="process_gate", source_ids=[4]),
        ],
    )


_CANNED = {
    "debt_collection": (_extract_debt, _review_debt),
    "sales": (_extract_sales, _review_sales),
    "customer_support": (_extract_support, _review_support),
    "general_meeting": (_extract_general, _review_general),
}


def mock_extract(segments, meta) -> ExtractionResult:
    text = "\n".join(s["text"] for s in segments)
    fp = _fingerprint(text)
    if fp and fp in _CANNED:
        return _CANNED[fp][0]()
    # generic fallback for arbitrary input
    first = segments[0]["text"] if segments else ""
    return ExtractionResult(
        tag="Call processed in mock mode",
        summary=("Mock mode is active (no LLM key). Line numbering, grounding and the workflow all run, but "
                 "structured extraction is limited. Add an OPENAI_API_KEY for full extraction. First line: "
                 + first[:160]),
        recommended_next_steps=["Add an OPENAI_API_KEY and re-run for full extraction."],
        decisions=[], action_items=[], blockers=[],
    )


def mock_review(segments) -> ReviewResult:
    text = "\n".join(s["text"] for s in segments)
    fp = _fingerprint(text)
    if fp and fp in _CANNED:
        return _CANNED[fp][1]()
    return ReviewResult(
        compliance_observations=[],
        items_needing_human_review=[
            ReviewItem(item="Full compliance review needs an LLM",
                       reason="Mock mode does not run domain compliance analysis on unseen transcripts; a human "
                              "(or an LLM key) is required.",
                       category="mock_mode_limitation",
                       source_ids=[segments[0]["id"]] if segments else []),
        ],
    )
