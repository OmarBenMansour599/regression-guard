# ADR 0003: Significance-aware regression gating

Status: Accepted (2026-11-09)

## Context
Golden datasets are small (~60-100 cases): one case is ~1-1.7 points, and LLM outputs are nondeterministic, so fixed thresholds (warn 3%, critical 8%) alone cause false alarms.

## Decision
- Thresholds are configurable per metric, in the metric's natural unit (absolute pp for rates, relative % for latency/tokens/cost).
- A CRITICAL verdict requires the delta to exceed the threshold AND evidence: significance (exact McNemar on paired per-case outcomes, default alpha 0.10) or a minimum number of regressed cases. WARN uses the plain threshold. Mode is configurable (`gate_mode: threshold | significant`).
- Hard rules (e.g. schema validity floor, cases tagged `critical`) can fail a run regardless.
- Reports state when a comparison is underpowered instead of implying certainty. Every verdict carries a machine-readable reason.
- Optional `n_samples` per case to identify flaky cases.

## Consequences
+ Fewer false alarms, more trustworthy gate.
- Small real regressions may be reported as inconclusive; mitigated by growing the dataset from real failures.
