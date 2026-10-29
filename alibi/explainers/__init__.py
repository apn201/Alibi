"""The explainer registry: every source of evidence, discovered by module name.

Each module `alibi.explainers.<source_id>` exposes `EXPLAINER` (an object with id, title,
kind, attribution, lamp and evaluate(ctx) -> Finding, see base.py). Modules are imported
defensively: a source whose module is missing or fails to import is registered as a stub
that always answers "unavailable", so the service runs with whatever has been built.
"""

from __future__ import annotations

import importlib
import logging

from .. import config
from .base import Context, Finding

log = logging.getLogger("alibi.explainers")

ORDER = [s["id"] for s in config.SOURCES if s["id"] != "profile"]
# How much a missing source lowers confidence: sea state is the core explainer.
STUB_PENALTY = {"sea_state": 0.2, "ice": 0.05}


class Stub:
    def __init__(self, meta: dict, reason: str):
        self.id, self.title, self.kind = meta["id"], meta["title"], meta["kind"]
        self.attribution, self.lamp, self.reason = meta["attribution"], meta["lamp"], reason

    def evaluate(self, ctx: Context) -> Finding:
        if self.kind == "identity":
            return Finding(self.id, "identity_context_only", "Identity lists were not checked in this build.")
        return Finding(self.id, "unavailable", "This source is not available in this build.", 0.0,
                       STUB_PENALTY.get(self.id, 0.1), self.lamp, details={"reason": self.reason})


def _load(meta: dict):
    try:
        mod = importlib.import_module(f"{__name__}.{meta['id']}")
        ex = getattr(mod, "EXPLAINER", None)
        if ex is None:  # fall back to a class with the right id
            for v in vars(mod).values():
                if isinstance(v, type) and getattr(v, "id", None) == meta["id"] and hasattr(v, "evaluate"):
                    ex = v()
                    break
        if ex is None:
            raise AttributeError("no EXPLAINER")
        if not hasattr(ex, "lamp"):
            ex.lamp = meta["lamp"]
        return ex, True
    except Exception as e:  # noqa: BLE001 - a broken source must not take the service down
        log.warning("explainer %s unavailable: %s", meta["id"], e)
        return Stub(meta, f"{type(e).__name__}: {e}"), False


REGISTRY: dict = {}
LOADED: dict[str, bool] = {}


def registry() -> dict:
    if not REGISTRY:
        for meta in config.SOURCES:
            if meta["id"] != "profile":
                REGISTRY[meta["id"]], LOADED[meta["id"]] = _load(meta)
    return REGISTRY
