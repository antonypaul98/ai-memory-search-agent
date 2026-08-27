# Token Efficiency + User Fit Doctrine

**Status:** Product requirement, not optional optimization.

The system should spend the **minimum sufficient tokens** needed to produce the answer the user actually wanted. Saving tokens is not a success if it makes the answer incomplete; adding detail is not a success if the user considers it noise.

## 1. Minimum-sufficient-token rule

Every request should minimize total token consumption across both context and model output:

- Context Router packs only evidence that fits the explicit context budget.
- Model Router uses task-specific output budgets instead of a single oversized default.
- `max_output_tokens` remains a hard user/application ceiling.
- `verbosity=detailed` is an explicit escape hatch that keeps the full ceiling.
- automatic mode learns per-user, per-task output length from feedback.
- deterministic routing, feedback, surveys, accounting, and preference learning use **zero LLM calls**.
- do not add hidden model calls merely to classify ordinary requests when deterministic routing is sufficient.
- keep cache/dedup/reuse paths ahead of repeated generation.
- measure prompt, completion, context, and wasted/rejected tokens separately.

The long-term KPI is **useful answer value per token**, not simply the smallest token count.

## 2. User-expectation rule

A route is successful only when the output matches the user's intent, not merely when a provider returned HTTP 200.

Current signals:

- explicit verbosity: auto / concise / balanced / detailed;
- task type: general / fast / reasoning / coding / summarization / extraction;
- rating 1–5;
- structured issues: too long, too short, incorrect, missing detail, wrong tone, wrong format, irrelevant, slow;
- optional description of what the user expected;
- periodic survey answers.

Length feedback updates only the user's own task-specific output budget. Other feedback is retained as structured signal for future tone/format/model/context scorecards. Do not send raw private feedback into unrelated model prompts.

## 3. Feedback cadence

Do not annoy users with a modal after every answer. The default lightweight survey offer appears every fifth routed interaction. The UI should also allow feedback at any time.

Surveys are deterministic/static by default so asking for feedback does not itself consume AI tokens.

## 4. Reward doctrine

Users should receive value for helping improve the system, but rewards must not bias ratings.

Current v0 rewards:

- quick answer feedback: **5 feedback credits**;
- completed short survey: **20 feedback credits**;
- default reward cap: **100 credits/day/user**;
- duplicate feedback on the same interaction is not rewarded twice;
- a 1-star response earns the same participation reward as a 5-star response.

This ensures we pay for **signal**, not praise.

The ledger and balance are implemented now. Before public launch, credits should be connected to a concrete redemption catalog such as platform-funded premium routing, advanced benchmark/audit features, or subscription discounts. Redemption economics must be based on actual unit costs and abuse controls rather than a made-up token exchange rate.

## 5. What we measure next

- answer satisfaction vs output token count;
- retries/re-prompts after an answer (a hidden sign the first answer failed);
- completion tokens saved against requested caps;
- context tokens supplied vs evidence actually cited/used;
- user-specific preferred answer length by task;
- model/context route satisfaction score;
- failure, fallback, latency, and cost per successful answer;
- survey completion and reward abuse rates.

The router should eventually optimize **quality × trust × speed × user fit / total cost**, where token use is one major cost rather than the only objective.
