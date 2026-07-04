"""
Validation / eval suite — runs with NO API key (mock mode) so any reviewer can
run it in seconds. Checks the invariants that make the output trustworthy.

Run:  cd backend && FORCE_MOCK=1 python test_pipeline.py
(or:  python -m pytest test_pipeline.py -q  after `pip install pytest`)
"""
import os

os.environ["FORCE_MOCK"] = "1"  # force deterministic mock before importing agent

import agent  # noqa: E402
from samples import SAMPLES  # noqa: E402

assert not agent.USE_LLM, "test suite must run in mock mode (set FORCE_MOCK=1)"


def _final(key):
    events = list(agent.run_stream(SAMPLES[key]["transcript"], SAMPLES[key]["meeting_date"]))
    return [e for e in events if e["node"] == "result"][0]["result"]


def test_domain_routing():
    for key in SAMPLES:
        assert _final(key)["domain"] == key, f"routing failed for {key}"


def test_every_item_is_grounded():
    """Every cited source_id must exist; evidence must be rebuilt from those lines."""
    for key in SAMPLES:
        r = _final(key)
        seg_ids = set(range(1, r["segment_count"] + 1))
        for bucket in ("decisions", "action_items", "blockers", "compliance_observations"):
            for it in r[bucket]:
                for sid in it["source_ids"]:
                    assert sid in seg_ids, f"{key}/{bucket}: bogus id {sid}"
                if it["source_ids"]:
                    assert it["evidence"].strip(), f"{key}/{bucket}: empty evidence"


def test_date_resolution():
    """The sharp date tests from the notebook: relative phrases -> concrete dates."""
    debt = _final("debt_collection")
    dues = {a["due"] for a in debt["action_items"]}
    assert "2026-08-15" in dues, "'15th of next month' should resolve to 2026-08-15"
    assert "2026-07-03" in dues, "'Friday' should resolve to 2026-07-03"

    gen = _final("general_meeting")
    gdues = {a["due"] for a in gen["action_items"]}
    assert "2026-07-10" in gdues, "'end of next week' should resolve to 2026-07-10"


def test_no_guessed_owner():
    """Owner-less tasks must stay null (the 'don't guess' rule)."""
    sales = _final("sales")
    proc = [a for a in sales["action_items"] if "procurement" in a["task"].lower()]
    assert proc and proc[0]["owner"] is None, "procurement task owner must be null"


def test_human_review_populated():
    for key in ("debt_collection", "sales", "customer_support", "general_meeting"):
        assert len(_final(key)["items_needing_human_review"]) >= 1, f"{key}: expected review items"


def test_fabricated_citation_is_caught():
    """The anti-hallucination gate: a bogus line id becomes an unverified_citation."""
    segs, lookup, meta = agent.ingest(SAMPLES["debt_collection"]["transcript"], "2026-07-01")
    ex = agent.extract(segs, "", meta)
    rev = agent.review(segs, "")
    ex.action_items[0].source_ids = [999]  # line 999 does not exist
    items = agent.ground_all(ex, rev, lookup)
    flagged = [i for i in items if i.category == "unverified_citation"]
    assert flagged, "a fabricated citation must be escalated to human review"
    assert ex.action_items[0].evidence == "", "no evidence should be built from a fake line"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} checks passed.")
