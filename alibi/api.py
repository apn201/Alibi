"""The HTTP API, everything under /api/v1. `alibi-openapi.yaml` is the published contract.

Errors always use the Error shape: validation -> 400, body over the limit -> 413, a request
that is valid but cannot be assessed (too short a track, no positions in the event window)
-> 422, unknown assessment -> 404. CORS is open: the demo GUI is served from another port.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import API_VERSION, MODEL_VERSION, config, ledger, profiles
from .assess import BadRequest, Unassessable, assess
from .explainers import LOADED, registry
from .schemas import (Assessment, AssessmentOptions, AssessmentRequest, BatchError, BatchRequest, Error, Health, Source)

log = logging.getLogger("alibi.api")
BASE = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = time.time()
    profiles.get()
    registry()
    ledger.init()
    try:  # warm the lazily loaded context layers so the first request is as fast as the rest
        from .explainers import identity, notices, place
        place.restriction_areas(), notices.snapshots(), identity.eu_list(), identity.gur_list()
        # one throw-away assessment loads whatever the other explainers (e.g. the env cache) load lazily
        t0 = int(time.time()) - 86400
        assess(AssessmentRequest.model_validate({"track": [
            {"timestamp": t0 + 60 * i, "latitude": 59.7, "longitude": 24.5 + 0.003 * i,
             "sog_knots": 12.0 if i < 50 else 4.0} for i in range(60)]}))
    except Exception as e:  # noqa: BLE001
        log.warning("warm-up: %s", e)
    log.info("ALIBI ready in %.1f s", time.time() - t)
    yield


app = FastAPI(title="ALIBI Assessment API", version=API_VERSION, lifespan=lifespan,
              summary="Evidence-backed triage for unusual maritime events",
              description="ALIBI (Automatic Lookout for Irregular Baltic Itineraries). The published contract is "
                          f"[{BASE}/openapi.yaml]({BASE}/openapi.yaml). An unexplained assessment is not a claim of "
                          "hostile intent.",
              openapi_url=f"{BASE}/openapi.json", docs_url=f"{BASE}/docs", redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ERRORS = {400: {"model": Error, "description": "Invalid request"},
          413: {"model": Error, "description": "Payload too large"},
          422: {"model": Error, "description": "Valid but cannot be assessed"}}


def _error(status: int, error: str, message: str, details: dict | None = None) -> JSONResponse:
    body = {"error": error, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status)


@app.middleware("http")
async def limit_body(request: Request, call_next):
    if request.method == "POST":
        limit = config.MAX_BATCH_BYTES if request.url.path.endswith("/batch") else config.MAX_BODY_BYTES
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > limit:
            return _error(413, "payload_too_large", f"The request body exceeds {limit // (1024 * 1024)} MB.")
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def on_validation(request: Request, exc: RequestValidationError):
    errs = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return _error(400, "invalid_request", "The request does not match the AssessmentRequest schema.", {"errors": errs[:50]})


@app.exception_handler(StarletteHTTPException)
async def on_http(request: Request, exc: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _error(exc.status_code, code, str(exc.detail))


def _run(req: AssessmentRequest, options=None, persist: bool = True) -> dict:
    result = assess(req, options)
    if persist:
        try:
            result["audit_reference"] = ledger.reference(result["assessment_id"])
            ledger.record(req.model_dump(mode="json", exclude_none=True), result)
        except Exception as e:  # noqa: BLE001 - an unwritable ledger degrades, it does not fail the answer
            log.warning("ledger write failed: %s", e)
            result["audit_reference"] = None
    return result


@app.get(f"{BASE}/health", response_model=Health, tags=["service"])
def health():
    p = profiles.get()
    deps = {"profiles": "ok" if p.ok and p.segments_ok else "degraded" if p.ok else "unavailable",
            "ledger": "ok" if ledger.init() else "unavailable",
            "envcache": "ok" if config.ENVCACHE.exists() and any(config.ENVCACHE.iterdir()) else "unavailable"}
    registry()
    deps["explainers"] = "ok" if all(LOADED.values()) else "degraded"
    status = "ok" if all(v == "ok" for v in deps.values()) else "degraded"
    return {"status": status, "api_version": API_VERSION, "model_version": MODEL_VERSION,
            "profile_version": config.PROFILE_VERSION, "dependencies": deps}


@app.get(f"{BASE}/sources", response_model=list[Source], tags=["service"])
def sources():
    registry()
    return [{**s, "available": s["id"] == "profile" or LOADED.get(s["id"], False)} for s in config.SOURCES]


@app.post(f"{BASE}/assessments", response_model=Assessment, response_model_exclude_none=False, tags=["assessments"],
          responses=ERRORS, summary="Assess an unusual AIS event (event mode) or a track (track mode)")
def create_assessment(req: AssessmentRequest):
    try:
        return _run(req)
    except BadRequest as e:
        return _error(400, e.error, e.message, e.details)
    except Unassessable as e:
        return _error(422, e.error, e.message, e.details)


@app.post(f"{BASE}/assessments/batch", response_model=list[Assessment | BatchError], tags=["assessments"],
          responses=ERRORS, summary="Assess several requests under one set of options (GUI re-runs)")
def create_batch(batch: BatchRequest):
    over = batch.options.model_dump(exclude_unset=True) if batch.options else {}
    out = []
    for i, req in enumerate(batch.requests):
        base = req.options.model_dump() if req.options else {}
        opts = AssessmentOptions.model_validate({**base, **over}) if base or over else None
        try:
            out.append(_run(req, opts, persist=batch.persist))
        except Unassessable as e:
            out.append({"index": i, "error": e.error, "message": e.message, "details": e.details or None})
    return out


@app.get(f"{BASE}/assessments/{{assessment_id}}", response_model=Assessment, tags=["assessments"],
         responses={404: {"model": Error, "description": "Assessment not found"}})
def get_assessment(assessment_id: str):
    r = ledger.get(assessment_id)
    if r is None:
        return _error(404, "not_found", f"No assessment {assessment_id} in the ledger.")
    return r


@app.get(f"{BASE}/openapi.yaml", include_in_schema=False)
def openapi_yaml():
    return PlainTextResponse(Path(config.OPENAPI_YAML).read_text(encoding="utf-8"), media_type="application/yaml")


@app.get(BASE, include_in_schema=False)
def index():
    return {"name": "ALIBI Assessment API", "api_version": API_VERSION, "docs": f"{BASE}/docs",
            "contract": f"{BASE}/openapi.yaml", "health": f"{BASE}/health"}
