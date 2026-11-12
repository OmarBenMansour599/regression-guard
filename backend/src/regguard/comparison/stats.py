"""Small exact statistics for paired pass/fail outcomes. Pure Python (no scipy).

McNemar's test only looks at *discordant* pairs: cases whose outcome changed between
baseline and candidate. With ``b`` regressions (pass->fail) and ``c`` improvements
(fail->pass), under "no real change" each flip is equally likely to go either way, so
``b ~ Binomial(b + c, 0.5)``. The one-sided p-value is ``P(X >= b)``: the chance of seeing
at least this many regressions among the flips if nothing really changed.

One-sided on purpose: the gate asks "did it get worse?", not "did it change?".
"""

import math


def binomial_tail(k: int, n: int) -> float:
    """``P(X >= k)`` for ``X ~ Binomial(n, 0.5)``, computed exactly with integers."""
    if n < 0 or k < 0:
        raise ValueError("k and n must be non-negative")
    if k == 0:
        return 1.0
    if k > n:
        return 0.0
    hits: int = sum(math.comb(n, i) for i in range(k, n + 1))
    return hits / (1 << n)


def mcnemar_one_sided(regressed: int, improved: int) -> float:
    """Exact one-sided McNemar p-value for "the candidate is worse". 1.0 when nothing flipped."""
    if regressed < 0 or improved < 0:
        raise ValueError("counts must be non-negative")
    return binomial_tail(regressed, regressed + improved)


def min_regressions_for_significance(alpha: float) -> int:
    """Fewest one-way regressions (no improvements) that reach ``p < alpha``.

    With zero improvements p = 0.5**b, so alpha 0.10 needs 4 regressions, 0.05 needs 5.
    Used to tell people when a comparison simply cannot be significant (underpowered).
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    b = 1
    while 0.5**b >= alpha:
        b += 1
    return b
