## ❌ RegressionGuard: FAIL

**App** `t` · **prompt** `v2` (`bbbbbbbbbbbb`) vs baseline `main` (v1) · **model** `mock-model` · **dataset** `v1` · **cases** 30

### Why
- **FAIL** `critical_regression`: label_exact 100.0% → 90.0% (-10.0 pts), 3 regressed / 0 improved of 30, p=0.125
- **WARN** `critical_underpowered`: label_exact/account 100.0% → 85.7% (-14.3 pts), 1 regressed / 0 improved of 7, p=0.500: beyond the critical threshold but not enough evidence (needs p &lt; 0.1 or &gt;= 3 regressed cases)
- **WARN** `critical_underpowered`: label_exact/billing 100.0% → 87.5% (-12.5 pts), 1 regressed / 0 improved of 8, p=0.500: beyond the critical threshold but not enough evidence (needs p &lt; 0.1 or &gt;= 3 regressed cases)
- **WARN** `critical_underpowered`: label_exact/technical 100.0% → 87.5% (-12.5 pts), 1 regressed / 0 improved of 8, p=0.500: beyond the critical threshold but not enough evidence (needs p &lt; 0.1 or &gt;= 3 regressed cases)
- **FAIL** `critical_case_regressed`: Critical case email-0001 regressed (now failing: label_exact)

### Metrics
| Metric | Baseline | Candidate | Change | −/+ | p | Level |
|---|---:|---:|---:|---:|---:|---|
| `pass_rate` | 100.0% | 90.0% | -10.0 pts | 3/0 | 0.125 |  |
| `label_exact` | 100.0% | 90.0% | -10.0 pts | 3/0 | 0.125 | **CRITICAL** |
| `schema_valid` | 100.0% | 100.0% | +0.0 pts | 0/0 | 1.000 |  |
| `label_exact/account` | 100.0% | 85.7% | -14.3 pts | 1/0 | 0.500 | **CRITICAL** |
| `label_exact/billing` | 100.0% | 87.5% | -12.5 pts | 1/0 | 0.500 | **CRITICAL** |
| `label_exact/general` | 100.0% | 100.0% | +0.0 pts | 0/0 | 1.000 |  |
| `label_exact/technical` | 100.0% | 87.5% | -12.5 pts | 1/0 | 0.500 | **CRITICAL** |
| `latency_ms_p95` | 1000 | 1000 | +0% | – | – |  |
| `tokens_per_case` | 100 | 100 | +0% | – | – |  |

### Changed cases (3 regressed, 0 improved)
| Case | Category | Change | Now failing |
|---|---|---|---|
| `email-0001` 🔒 critical | billing | regressed | label_exact |
| `email-0002` | technical | regressed | label_exact |
| `email-0003` | account | regressed | label_exact |

<details><summary>Notes</summary>

- `statistical_power`: 30 paired case(s): one case = 3.3 points; at least 4 one-way regressions are needed for significance at alpha=0.1

</details>

<sub>RegressionGuard 0.1.0 · run `cand`</sub>
