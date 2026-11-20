"""Tiny inline SVG trend charts. Built only from numbers, so the output is safe to embed."""

from collections.abc import Sequence


def sparkline(values: Sequence[float], *, width: int = 160, height: int = 36) -> str:
    """A polyline of the values (oldest -> newest) with the last point marked. "" if < 2."""
    if len(values) < 2:
        return ""
    pad = 4
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = (width - 2 * pad) / (len(values) - 1)

    def y(v: float) -> float:
        return height - pad - (v - low) / span * (height - 2 * pad)

    points = " ".join(f"{pad + i * step:.1f},{y(v):.1f}" for i, v in enumerate(values))
    last_x, last_y = pad + (len(values) - 1) * step, y(values[-1])
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="trend of {len(values)} runs">'
        f'<polyline fill="none" stroke="currentColor" stroke-width="1.5" points="{points}"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="currentColor"/></svg>'
    )
