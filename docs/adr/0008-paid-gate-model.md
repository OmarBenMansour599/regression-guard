# ADR 0008: A paid model with pinned provider routing for the gate

Status: Accepted (2026-11-27)

## Context
The gate and the daily monitor ran on `google/gemma-4-26b-a4b-it:free`, which OpenRouter serves from one shared Google pool. On 2026-11-20, 11-22 and 11-24, that pool answered HTTP 503 to most requests, and the gate returned ERROR (fail closed) instead of a verdict. The outage switch and second pass (2026-11-24) limit the damage but cannot make an overloaded provider answer.

The paid model (same weights, without `:free`) is served by about 15 providers. Prices on 2026-11-27: about $0.09 per million input tokens and $0.30 per million output tokens. A 12-case gate run costs about $0.0005. The owner bought $10 of OpenRouter credits (one time; this also raises the free daily limit to 1,000 requests).

Providers run the model at different numeric precisions (int4, fp4, fp8, bf16). By default OpenRouter picks the cheapest one, so two runs of the same prompt could come from different precisions. That would create false regressions and fake drift: noise is exactly what this tool must avoid.

## Decision
- New prompt version **`v3`** = v1's instructions unchanged, model `google/gemma-4-26b-a4b-it`, with OpenRouter routing in `model.extra.provider`:
  - `quantizations: [bf16]`: one precision only, so answers do not depend on which provider is cheapest.
  - `data_collection: deny`: never route the emails to a provider that may train on them.
  - `require_parameters: true`: only providers that honour every request parameter. This guarantees JSON mode, the behaviour the gate checks; the v2 regression was a JSON-format bug.

  On 2026-11-27 this leaves **CoreWeave and Parasail**: PrimeIntellect and Venice serve bf16 but ignore `seed`. Two providers keep a fallback.
- The routing lives in the prompt file, so it is part of the prompt fingerprint: changing it is a reviewed change that the gate evaluates.
- Every run records **which provider answered** (`served_providers`) and **what it cost** (`cost_usd`, fresh calls only), as reported by OpenRouter. If quality moves when the provider changes, the run says so.
- Rollout through the gate itself:
  1. PR 1 adds v3; the gate compares it with baseline `main` (v1 on the free model).
  2. PR 2 promotes a v3 run as the new `main`. The PR gate and the daily monitor then use v3 automatically.
- The LLM judge stays on its free model. It is non-gating and off in PR runs; revisit if it fails often.

## Consequences
+ Gate and monitor no longer depend on the overloaded free pool.
+ Consistent precision keeps the gate's statistics meaningful.
+ Costs are visible on every run (CLI, run page, reports).
- A small real cost (about $0.20 a year at one monitor run a day plus a few PRs a week).
- Only two eligible providers today. If both disappear, runs fail with "no provider available" until the routing is relaxed, and relaxing it is a reviewed change to the prompt file.
- Prompts derived from v1 for future experiments should start from v3, so that a comparison measures the prompt change and not the model switch.
