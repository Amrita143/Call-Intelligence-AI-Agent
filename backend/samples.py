"""Sanitized/fake sample transcripts (from app.ipynb) used for the demo and tests."""

MEETING_DATE = "2026-07-01"

SAMPLES = {
    "debt_collection": {
        "label": "Debt collection — settlement split",
        "meeting_date": MEETING_DATE,
        "transcript": """[00:00] Agent: Thank you for calling back, this call is recorded for quality and compliance. This is Marcus with Anderson Recovery — this is an attempt to collect a debt and any information obtained will be used for that purpose. Am I speaking with James Whitfield?
[00:09] Consumer: Yeah, this is James.
[00:11] Agent: Thanks. To verify, can you confirm your full name and the last four of your SSN?
[00:16] Consumer: James Whitfield, and it's 4412.
[00:20] Agent: Perfect. James, our records show a past-due balance of $2,340 on your Summit Card account. How can we take care of that today?
[00:28] Consumer: I honestly can't do the full amount. I lost my job in March.
[00:33] Agent: I understand. I may be able to offer a settlement. If you can do $1,400 today we can consider it settled in full.
[00:41] Consumer: That's still too much right now. Could I do $700 now and $700 next month?
[00:47] Agent: Let me note that — $700 today and $700 on the 15th of next month. I'll need a supervisor to approve the settlement split, I'll follow up by Friday.
[00:56] Consumer: Okay. And this won't go on my credit as unpaid?
[01:00] Agent: Once both payments post, we'll mark it settled and close the account. I'll send written confirmation.""",
    },
    "sales": {
        "label": "Sales — Pro plan pending approvals",
        "meeting_date": MEETING_DATE,
        "transcript": """[00:00] Rep: Thanks for hopping on, Dana. Last time your team was hitting limits on the Starter plan — did the dashboards help since the trial?
[00:08] Dana: They did. The analytics are the main reason we'd move forward. We've got about 30 people who'd need seats now.
[00:15] Rep: Got it. For 30 seats I'd put you on Pro. List is $40 a seat, but I can do $32 if we sign an annual term.
[00:23] Dana: Pricing's the sticking point. Anything over $25k a year has to clear procurement, and legal needs to review the data terms.
[00:31] Rep: Understood. Let's plan on Pro at the annual rate, pending those approvals. I'll send the proposal and the DPA today and loop in our security team for the review.
[00:40] Dana: Who's chasing procurement on your side?
[00:42] Rep: That'd be on your side actually — can someone there own it, otherwise it'll stall?
[00:47] Dana: I'll find out who. Let's regroup early next week.
[00:50] Rep: Perfect, I'll set up the follow-up and aim to have everything wrapped by end of the month.""",
    },
    "customer_support": {
        "label": "Customer support — duplicate charge",
        "meeting_date": MEETING_DATE,
        "transcript": """[00:00] Agent: Thanks for calling TechCare support, this is Priya, is it alright if I record this call for quality?
[00:06] Customer: Sure. I've been charged twice for my subscription this month and I want it fixed.
[00:12] Agent: I'm sorry about that. Let me pull up your account — can you confirm the email and billing zip on file?
[00:19] Customer: jordan.k@example.com, zip 60614.
[00:24] Agent: Thank you, that verifies you. I do see two charges on the 3rd. That's a duplicate on our end, so a refund is warranted.
[00:32] Customer: Good. How fast?
[00:34] Agent: Normally three to five business days. I'll be honest though — our billing tool's been flaky since yesterday's outage, so I can't fully confirm it processed.
[00:43] Customer: That's not reassuring. I need this resolved.
[00:46] Agent: I hear you. I don't have authority to expedite the refund myself, so I'm opening a priority ticket — case 55231 — and escalating to billing. I'll personally follow up with you tomorrow to confirm it went through.""",
    },
    "general_meeting": {
        "label": "General meeting — eng standup",
        "meeting_date": MEETING_DATE,
        "transcript": """[00:00] Mira: Quick standup. Raj, where's the payments webhook?
[00:04] Raj: I'll have the Stripe handler done by this week Wednesday, just testing left. I'm blocked on staging keys though, no access yet.
[00:12] Mira: I'll chase IT for your access today. Devi, the search reindex?
[00:17] Devi: Script's ready. I'll run it in prod this weekend, but our rule is prod changes need a second reviewer — not sure who's free.
[00:25] Mira: We'll go with Postgres full-text for now instead of Elasticsearch, the extra infra isn't worth it yet.
[00:31] Devi: Agreed. I'll aim to ship the reindex by end of next week if I get a reviewer.
[00:36] Mira: Last thing — the flaky CI. Someone should look at it soon, it's slowing everyone down.""",
    },
}
