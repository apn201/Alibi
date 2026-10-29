"""Small helpers shared by the explainers ALIBI ships (not part of the contract in base.py).

The deviation an explainer can account for is the speed drop D = expected - observed (kn).
An explainer that expects the ship to be slower by delta kn explains min(1, delta / D) of it,
and says so in the signature trace as a negative expected_delta_kn over the event window.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base import Context, Finding

SUPPORTS = 0.2  # explains >= this -> supports_explanation (BUILD.md)


def deviation_kn(ctx: Context) -> float | None:
    if ctx.expected_kn is None or ctx.observed_kn is None:
        return None
    return ctx.expected_kn - ctx.observed_kn


def share(delta_kn: float, ctx: Context) -> float:
    d = deviation_kn(ctx)
    if d is None or d <= 0 or delta_kn <= 0:
        return 0.0
    return float(min(1.0, delta_kn / d))


def window_delta(ctx: Context, delta_kn: float) -> list[tuple[int, float]]:
    """A step of -delta over the event window, ramped over a minute at each end."""
    return [(ctx.event_start - 60, 0.0), (ctx.event_start, -delta_kn), (ctx.event_end, -delta_kn),
            (ctx.event_end + 60, 0.0)]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unavailable(source_id: str, summary: str, lamp=None, penalty: float = 0.1, **details) -> Finding:
    return Finding(source_id, "unavailable", summary, 0.0, penalty, lamp, details=details)


def no_slowdown(source_id: str, lamp=None) -> Finding:
    return Finding(source_id, "neutral", "There is no speed drop for this source to explain.", lamp=lamp)
