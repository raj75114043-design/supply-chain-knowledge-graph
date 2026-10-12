"""FastAPI service.

  POST /v1/ask                     GraphRAG question answering
  GET  /v1/events                  risk events with revenue at risk
  GET  /v1/events/{event_id}       full impact analysis with explanation paths
  GET  /v1/suppliers/{id}/stress   loss of a supplier for its time to recover
  GET  /v1/resolve?name=...        entity resolution candidates for a company name
  GET  /v1/concentration, /v1/sanctions, /v1/single-source
  GET  /health, /ready, /metrics
"""
from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field

from sckg import analytics as A
from sckg import logging_setup
from sckg.config import get_settings
from sckg.pipeline import get_build
from sckg.qa import QA

logging_setup.configure()
app = FastAPI(title="Supply-Chain Knowledge Graph", version="1.0.0")
REQ = Counter("sckg_http_requests_total", "HTTP requests", ["path", "status"])
ASK = Counter("sckg_questions_total", "Questions", ["intent"])


@app.middleware("http")
async def ctx(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    tok = logging_setup.request_id.set(rid)
    try:
        resp = await call_next(request)
    finally:
        logging_setup.request_id.reset(tok)
    resp.headers["X-Request-ID"] = rid
    REQ.labels(request.url.path.split("/")[2] if request.url.path.startswith("/v1/") else request.url.path, resp.status_code).inc()
    return resp


def auth(x_api_key: str | None = Header(default=None)):
    if x_api_key not in get_settings().api_keys:
        raise HTTPException(401, "Invalid or missing API key")


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=400, examples=["What is the impact of the Kyushu earthquake?"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"status": "ready", **get_build().stats}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/ask", dependencies=[Depends(auth)])
def ask(q: Ask):
    r = QA(get_build().kg).ask(q.question)
    ASK.labels(r["intent"]).inc()
    return r


@app.get("/v1/events", dependencies=[Depends(auth)])
def events():
    kg = get_build().kg
    return [{"event_id": e, **{k: kg.g.nodes[e][k] for k in ("event_type", "weeks", "date")},
             "revenue_at_risk_musd": A.event_impact(kg, e)["revenue_at_risk_musd"]} for e in kg.nodes_of("Event")]


@app.get("/v1/events/{event_id}", dependencies=[Depends(auth)])
def event(event_id: str):
    kg = get_build().kg
    if event_id not in kg.g or kg.kind(event_id) != "Event":
        raise HTTPException(404, "event not found")
    r = A.event_impact(kg, event_id)
    r["explanations"] = [A.explain_path(kg, event_id, p["binding_part"]) for p in r["products"] if p["loss_weeks"] > 0][:3]
    return r


@app.get("/v1/suppliers/{supplier_id}/stress", dependencies=[Depends(auth)])
def stress(supplier_id: str):
    kg = get_build().kg
    if supplier_id not in kg.g or kg.kind(supplier_id) != "Supplier":
        raise HTTPException(404, "supplier not found")
    return A.stress_test(kg, supplier_id)


@app.get("/v1/resolve", dependencies=[Depends(auth)])
def resolve(name: str):
    r = get_build().resolver
    return [{"entity_id": e, "name": r.entities[e].name, "score": s} for e, s in r.candidates(name, 5)]


@app.get("/v1/concentration", dependencies=[Depends(auth)])
def concentration():
    return A.hidden_concentration(get_build().kg)


@app.get("/v1/sanctions", dependencies=[Depends(auth)])
def sanctions():
    return A.sanctions_exposure(get_build().kg)


@app.get("/v1/single-source", dependencies=[Depends(auth)])
def single_source():
    return A.single_source_parts(get_build().kg)
