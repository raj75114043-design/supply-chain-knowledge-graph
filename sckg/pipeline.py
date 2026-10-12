"""End-to-end build: raw ERP + documents + sanctions list → extraction → entity resolution → screening → graph."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sckg.config import Settings, get_settings
from sckg.extract import Triple, extract
from sckg.graph import KG, build
from sckg.llm import build_llm
from sckg.resolve import Entity, Resolver, score

log = logging.getLogger("sckg.pipeline")
SANCTIONS_THRESHOLD = 0.9


def load_raw(raw_dir: str | Path) -> dict:
    raw = Path(raw_dir)
    return {"erp": json.loads((raw / "erp.json").read_text()),
            "documents": [json.loads(x) for x in (raw / "documents.jsonl").read_text().splitlines() if x.strip()],
            "sanctions": json.loads((raw / "sanctions.json").read_text()),
            "regions": json.loads((raw / "regions.json").read_text())}


def places(regions: list[dict]) -> dict[str, str]:
    return {r["city"]: "city" for r in regions} | {r["region"]: "region" for r in regions}


def screen(entities: dict[str, dict], sanctions: list[dict]) -> list[dict]:
    matches = []
    for eid, e in entities.items():
        names = [e["name"], *e.get("names", [])]
        for s in sanctions:
            sc = max(score(n, [s["name"], *s["aliases"]]) for n in names)
            if sc >= SANCTIONS_THRESHOLD:
                matches.append({"entity_id": eid, "list_id": s["list_id"], "list_name": s["name"], "program": s["program"], "score": round(sc, 3)})
    return matches


@dataclass
class Build:
    kg: KG
    triples: list[Triple]
    resolution: dict[str, tuple[str | None, float]]
    resolver: Resolver
    sanctions_matches: list[dict]
    raw: dict
    stats: dict = field(default_factory=dict)


def run(settings: Settings | None = None) -> Build:
    settings = settings or get_settings()
    t0 = time.perf_counter()
    raw = load_raw(settings.raw_dir)
    llm = build_llm(settings) if settings.use_llm_extraction else None
    triples, xstats = extract(raw["documents"], places(raw["regions"]), llm)
    resolver = Resolver([Entity(s["supplier_id"], s["legal_name"], set()) for s in raw["erp"]["suppliers"]])
    org_args = set()
    for t in triples:
        if t.relation in ("SUPPLIES", "SUBSIDIARY_OF"):
            org_args |= {t.head, t.tail}
        elif t.relation == "LOCATED_IN":
            org_args.add(t.head)
        elif t.relation == "AFFECTS" and t.attrs.get("target_kind") == "supplier":
            org_args.add(t.tail)
    org_args |= {a for t in triples if t.relation == "CO_SUPPLY" for a in (t.head, t.tail)}
    supply_ctx = {a for t in triples if t.relation in ("SUPPLIES", "CO_SUPPLY") for a in (t.head, t.tail)} | \
                 {t.tail for t in triples if t.relation == "AFFECTS" and t.attrs.get("target_kind") == "supplier"}
    resolution = resolver.resolve_all(sorted(org_args), supply_ctx)
    facts, unresolved = [], []
    for t in triples:
        prov = {"doc_id": t.doc_id, "sentence": t.sentence, "extractor": t.extractor, "confidence": t.confidence}
        if t.relation == "AFFECTS":
            tail = resolution[t.tail][0] if t.attrs.get("target_kind") == "supplier" else t.tail
            if tail:
                facts.append({"head": f"EV:{t.head}", "relation": "AFFECTS", "tail": tail, "attrs": t.attrs, "provenance": prov})
            continue
        h = resolution.get(t.head, (None, 0))[0]
        tl = resolution.get(t.tail, (None, 0))[0] if t.relation != "LOCATED_IN" else t.tail
        if t.relation == "CO_SUPPLY" and h and tl:   # orient: the ERP tier-1 company is the customer
            erp_ids = {s["supplier_id"] for s in raw["erp"]["suppliers"]}
            if (h in erp_ids) == (tl in erp_ids):
                unresolved.append(t.as_dict())
                continue
            sup, cust = (tl, h) if h in erp_ids else (h, tl)
            facts.append({"head": sup, "relation": "SUPPLIES", "tail": cust, "attrs": t.attrs, "provenance": prov})
            continue
        if h and tl:
            facts.append({"head": h, "relation": t.relation, "tail": tl, "attrs": t.attrs, "provenance": prov})
        else:
            unresolved.append(t.as_dict())
    entities = {eid: {"name": e.name, "names": sorted(e.names), "source": e.source, "tier": 1 if e.source == "erp" else None}
                for eid, e in resolver.entities.items()}
    matches = screen(entities, raw["sanctions"])
    kg = build(raw["erp"], raw["regions"], facts, entities, matches)
    stats = {"documents": len(raw["documents"]), "triples": len(triples), "facts": len(facts), "unresolved": len(unresolved),
             "entities_from_documents": sum(1 for e in entities.values() if e["source"] == "documents"),
             "review_queue": len(resolver.review_queue), "sanctions_matches": len(matches), "build_ms": round((time.perf_counter() - t0) * 1000, 1),
             **xstats, **kg.stats()}
    log.info("graph_built", extra={k: v for k, v in stats.items() if not isinstance(v, dict)})
    return Build(kg, triples, resolution, resolver, matches, raw, stats)


@lru_cache(maxsize=4)
def _cached(sig: tuple) -> Build:
    return run()


def get_build() -> Build:
    return _cached(tuple(os.getenv(k, "") for k in ("RAW_DIR", "LLM_EXTRACTION", "GROQ_API_KEY", "LLM_PROVIDER")))
