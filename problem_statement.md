# Problem Statement

## The problem

Teams run calls and meetings all day: sales calls, support calls, debt-collection
calls, internal standups. When a call ends, someone still has to work out what
actually happened. What was decided? Who agreed to do what, and by when? What's
stuck? Did anyone say something risky or against policy? And often the hardest
one: where in the conversation did that happen, so we can trust it?


The obvious fix is to hand the transcript to an LLM and ask for a summary. That's
fast, but you can't rely on it. Models make up action items that were never
agreed, assign them to people who never volunteered, guess dates, and state
serious things ("the agent offered to waive the fee") with full confidence and no
proof. On a support or collections call, a confident wrong answer is worse than no
answer.

So the real problem isn't "summarise a call." It's "turn a call into notes a
person can actually rely on" — where every point is backed by a specific line of
the transcript, and anything the system isn't sure about is handed to a human
instead of guessed.

## What the system produces

For each transcript it returns one structured object:

- a short tag and a plain-language summary
- the decisions that were actually made
- action items, each with an owner, a start/due date where one was given, and the
  lines they came from
- blockers that are stopping progress
- compliance observations — things done right and things that are risky — marked
  Red, Yellow, or Green
- a list of items that need a human to look at them
- for every item, the exact transcript lines it is based on

Two rules make this trustworthy. First, nothing is stated without pointing back to
the transcript lines it came from, and those lines are pulled straight from the
original text, so the model can't quietly reword them. Second, whenever something
is unclear, risky, or beyond what software should decide, it goes into the
human-review list rather than being asserted as fact.

## When something goes to a human

The system is meant to be cautious. It sends an item for human review when, for
example:

- an action item has no clear owner, or its deadline is vague
- a customer's consent (say, to being recorded) isn't clearly given
- there might be a compliance problem
- a decision needs real judgement, or authority the system doesn't have
- the transcript contains sensitive information, personal or financial
- the conversation is simply unclear on the point

This list isn't fixed. The review step is told the kinds of things to watch for
and is free to flag anything else a sensible reviewer would want to check.

## A quick example

From a debt-collection call recorded on Wednesday 1 July 2026, these lines appear
in the transcript:

```
7: Consumer: That's still too much right now. Could I do $700 now and $700 next month?
8: Agent: Let me note that — $700 today and $700 on the 15th of next month. I'll need
   a supervisor to approve the settlement split, I'll follow up by Friday.
```

The system produces, among other things:

```
action item : Consumer to pay second $700 installment
              owner: James (consumer)   due: 2026-08-15   from line 8
action item : Follow up on supervisor approval for the settlement split
              owner: Marcus (agent)     due: 2026-07-03   from line 8
blocker     : Settlement split needs supervisor approval before it is final   from line 8
human review: Settlement split is beyond standard terms and needs a supervisor's sign-off
```

"The 15th of next month" is worked out to 2026-08-15 and "Friday" to 2026-07-03,
both measured from the meeting date. Nothing is invented, and every item points
back to the line it came from.

## Scope

In scope: a text transcript/audio input, structured notes out; line-level grounding; dates worked out from the conversation; domain-aware compliance checks; a human-review
queue.

Out of scope for now: memory across multiple calls. 
