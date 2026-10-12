"""Evaluation and quality gate.

    python -m sckg.eval.run --gate

1. Extraction + resolution — relation triples in gold entity space: precision / recall / F1, by relation and by phrasing
   (patterns the extractor was written for vs. unseen phrasing).
2. Entity resolution — B-cubed precision / recall on all gold mentions, including look-alike companies; ambiguous mentions
   routed to review count as singletons (not guessed).
3. Analytics agreement — the pipeline graph versus a graph built from gold facts: per-event affected products and revenue
   at risk, hidden concentration, sanctions exposure.
4. GraphRAG QA — golden questions generated from the gold graph; the answer must contain the expected facts.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sckg import analytics as A
from sckg.graph import build
from sckg.pipeline import get_build, screen
from sckg.qa import QA
from sckg.resolve import Entity, Resolver

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data" / "gold.json"
THRESHOLDS = {"extraction_precision": 0.95, "extraction_recall_seen": 0.95, "er_bcubed_f1": 0.95, "er_false_merges": 0,
              "event_products_match": 0.95, "concentration_match": 1.0, "sanctions_match": 1.0, "qa_accuracy": 0.9}


def gold_graph(raw: dict, gold: dict):
    ents = {eid: {"name": e["name"], "names": e["aliases"], "source": "erp" if eid.startswith("S") else "documents",
                  "tier": e["tier"]} for eid, e in gold["entities"].items() if not eid.startswith("Y")}
    facts = []
    for r in gold["relations"]:
        prov = {"doc_id": r["doc_id"], "extractor": "gold", "confidence": 1.0}
        if r["relation"] == "AFFECTS":
            facts.append({"head": f"EV:{r['event_type']}@{r['date']}", "relation": "AFFECTS", "tail": r["tail"],
                          "attrs": {"event_type": r["event_type"], "weeks": r["weeks"], "date": r["date"],
                                    "target_kind": "supplier" if "supplier" in r else "location"}, "provenance": prov})
        else:
            facts.append({"head": r["head"], "relation": r["relation"], "tail": r["tail"], "attrs": {"component": r.get("component")}, "provenance": prov})
    matches = [m for m in screen(ents, raw["sanctions"])]
    return build(raw["erp"], raw["regions"], facts, ents, matches)


def _to_gold_ids(b, gold) -> dict[str, str]:
    """Map pipeline entity ids (N00x for document-only companies) to gold ids by majority vote of their mentions."""
    by_mention = {m["mention"]: m["entity_id"] for m in gold["mentions"]}
    out = {}
    for eid, e in b.resolver.entities.items():
        votes = Counter(by_mention[n] for n in e.names | {e.name} if n in by_mention)
        out[eid] = votes.most_common(1)[0][0] if votes else (eid if e.source == "erp" else f"?{eid}")
    return out


def extraction_metrics(b, gold) -> dict:
    idmap = _to_gold_ids(b, gold)
    pred = set()
    for u, v, k, d in b.kg.g.edges(keys=True, data=True):
        if k in ("SUPPLIES", "SUBSIDIARY_OF"):
            pred.add((idmap.get(u, u), k, idmap.get(v, v)))
        elif k == "LOCATED_IN" and any(p.get("doc_id") for p in d["provenance"]):
            pred.add((idmap.get(u, u), k, v.replace("city:", "")))
        elif k == "AFFECTS":
            pred.add((b.kg.g.nodes[u]["event_type"], k, idmap.get(v, v).replace("region:", "").replace("city:", "")))
    gold_t, unseen = set(), set()
    for r in gold["relations"]:
        t = (r["event_type"], "AFFECTS", r["tail"]) if r["relation"] == "AFFECTS" else (r["head"], r["relation"], r["tail"])
        (unseen if r.get("phrasing") == "unseen" else gold_t).add(t)
    unseen -= gold_t
    all_gold = gold_t | unseen
    tp = pred & all_gold
    by_rel = {}
    for rel in ("SUPPLIES", "LOCATED_IN", "SUBSIDIARY_OF", "AFFECTS"):
        g, p = {t for t in all_gold if t[1] == rel}, {t for t in pred if t[1] == rel}
        by_rel[rel] = {"precision": round(len(g & p) / max(1, len(p)), 3), "recall": round(len(g & p) / max(1, len(g)), 3), "gold": len(g)}
    return {"extraction_precision": len(tp) / max(1, len(pred)), "extraction_recall": len(tp) / max(1, len(all_gold)),
            "extraction_recall_seen": len(pred & gold_t) / max(1, len(gold_t)), "extraction_recall_unseen": len(pred & unseen) / max(1, len(unseen)),
            "by_relation": by_rel, "missed": sorted(map(list, all_gold - pred)), "spurious": sorted(map(list, pred - all_gold))}


def er_metrics(b, gold) -> dict:
    erp = b.raw["erp"]["suppliers"]
    r = Resolver([Entity(s["supplier_id"], s["legal_name"], set()) for s in erp])
    rel_docs = {x["doc_id"] for x in gold["relations"] if x["relation"] == "SUPPLIES"}
    gm = {(m["doc_id"], m["mention"]): m["entity_id"] for m in gold["mentions"]}
    ctx = {m for (d, m) in gm if d in rel_docs}
    res = r.resolve_all([m for _, m in gm], ctx)
    pred = {k: (res[k[1]][0] or f"review:{k}") for k in gm}
    pc, tc = defaultdict(set), defaultdict(set)
    for k in gm:
        pc[pred[k]].add(k)
        tc[gm[k]].add(k)
    P = [len(pc[pred[k]] & tc[gm[k]]) / len(pc[pred[k]]) for k in gm]
    R = [len(pc[pred[k]] & tc[gm[k]]) / len(tc[gm[k]]) for k in gm]
    p, rr = sum(P) / len(P), sum(R) / len(R)
    false_merges = sum(1 for c in pc.values() if len({gm[k] for k in c}) > 1)
    lookalikes = {k: pred[k] for k in gm if gm[k].startswith("Y")}
    return {"er_bcubed_precision": p, "er_bcubed_recall": rr, "er_bcubed_f1": 2 * p * rr / (p + rr), "er_false_merges": false_merges,
            "er_review_queue": len(r.review_queue), "er_mentions": len(gm),
            "lookalikes_kept_separate": all(not v.startswith("S") for v in lookalikes.values())}


def analytics_metrics(b, truth) -> dict:
    ev_ok, rows = [], []
    for e in truth.nodes_of("Event"):
        t = A.event_impact(truth, e)
        p = A.event_impact(b.kg, e) if e in b.kg.g else {"products": [], "revenue_at_risk_musd": None}
        tp = {x["product"] for x in t["products"] if x["loss_weeks"] > 0}
        pp = {x["product"] for x in p["products"] if x["loss_weeks"] > 0}
        ok = tp == pp and t["revenue_at_risk_musd"] == p["revenue_at_risk_musd"]
        ev_ok.append(ok)
        rows.append({"event": e, "truth_revenue_at_risk": t["revenue_at_risk_musd"], "pipeline_revenue_at_risk": p["revenue_at_risk_musd"],
                     "match": ok})
    idmap = _to_gold_ids(b, json.loads(GOLD.read_text()))
    tc = {(c["company"], tuple(c["tier1_customers"])) for c in A.hidden_concentration(truth)}
    pc = {(idmap.get(c["company"], c["company"]), tuple(c["tier1_customers"])) for c in A.hidden_concentration(b.kg)}
    ts = {r["tier1_supplier"] for r in A.sanctions_exposure(truth)}
    ps = {r["tier1_supplier"] for r in A.sanctions_exposure(b.kg)}
    return {"event_products_match": sum(ev_ok) / len(ev_ok), "events": rows, "concentration_match": float(tc == pc),
            "concentration_truth": sorted(map(str, tc)), "concentration_pipeline": sorted(map(str, pc)), "sanctions_match": float(ts == ps)}


def golden_questions(truth) -> list[dict]:
    qs = []
    phr = {"flood": ["What is the impact of the Guangdong flood?", "How exposed are we to the flooding in Shenzhen and Dongguan?"],
           "earthquake": ["What is the impact of the Kyushu earthquake?"], "export restriction": ["How does the rare earth export restriction affect us?"],
           "fire": ["What is the impact of the fire at Tijuana Harness?"], "port strike": ["Does the Gdansk port strike affect production?"],
           "typhoon": ["What is the impact of the typhoon in Hsinchu?"]}
    for e in truth.nodes_of("Event"):
        r = A.event_impact(truth, e)
        for q in phr[truth.g.nodes[e]["event_type"]]:
            qs.append({"question": q, "expect_intent": "event_impact", "expect": [f"${r['revenue_at_risk_musd']}M"] if r["revenue_at_risk_musd"] else
                       ["Covered by inventory"]})
    for s, label in [("X03", "Formosa Wafer"), ("X02", "GREM"), ("X01", "Kunlun Lithium"), ("S03", "Kiyomi Semi")]:
        r = A.stress_test(truth, s)
        qs.append({"question": f"What happens if we lose {label}?", "expect_intent": "supplier_impact", "expect": [f"${r['revenue_at_risk_musd']}M"]})
    qs += [
        {"question": "Who supplies the lithium-ion cells?", "expect_intent": "suppliers_of", "expect": ["Volta Cell Systems", "Hwaseong Energy", "not independent"]},
        {"question": "Who supplies the drive motor?", "expect_intent": "suppliers_of", "expect": ["Rotorix", "Ganzhou Rare Earth Magnetics"]},
        {"question": "Which parts are single-sourced?", "expect_intent": "single_source", "expect": ["12 of 14", "BMS controller chip"]},
        {"question": "Do we have hidden sub-tier concentration?", "expect_intent": "concentration",
         "expect": ["Formosa Wafer Foundry", "Kunlun Lithium", "not independent"]},
        {"question": "Are we exposed to any sanctioned companies?", "expect_intent": "sanctions", "expect": ["Altai Mineral", "Rotorix", "Silesia Seating"]},
        {"question": "Which suppliers are most critical?", "expect_intent": "critical", "expect": ["Formosa Wafer Foundry"]},
        {"question": "Which products depend on Baltic Copper?", "expect_intent": "supplier_impact", "expect": ["Tijuana Harness", "Rotorix"]},
        {"question": "What is the capital of France?", "expect_intent": "unknown", "expect": ["I can answer questions about"]},
    ]
    return qs


def qa_metrics(b, truth) -> dict:
    qa, rows = QA(b.kg), []
    for g in golden_questions(truth):
        r = qa.ask(g["question"])
        ok = r["intent"] == g["expect_intent"] and all(x.lower() in r["answer"].lower() for x in g["expect"])
        rows.append({"question": g["question"], "ok": ok, "intent": r["intent"], **({} if ok else {"answer": r["answer"][:300], "expect": g["expect"]})})
    return {"qa_accuracy": sum(r["ok"] for r in rows) / len(rows), "qa_cases": len(rows), "qa_failures": [r for r in rows if not r["ok"]]}


def evaluate() -> dict:
    b = get_build()
    gold = json.loads(GOLD.read_text())
    truth = gold_graph(b.raw, gold)
    m = {**extraction_metrics(b, gold), **er_metrics(b, gold), **analytics_metrics(b, truth), **qa_metrics(b, truth), "build": b.stats}
    return m


def gate(m: dict) -> list[str]:
    out = []
    for k, thr in THRESHOLDS.items():
        if k == "er_false_merges":
            if m[k] > thr:
                out.append(f"{k}={m[k]}")
        elif m[k] < thr:
            out.append(f"{k}={m[k]:.3f} < {thr}")
    return out


def main() -> None:
    logging.disable(logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--out", default="reports/eval.json")
    a = ap.parse_args()
    m = evaluate()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(m, indent=2, default=str))
    show = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items() if not isinstance(v, (dict, list))}
    print(json.dumps(show, indent=2))
    print("by_relation", json.dumps(m["by_relation"]))
    print("missed", m["missed"], "spurious", m["spurious"])
    for e in m["events"]:
        print("event", e)
    for f in m["qa_failures"]:
        print("QA FAIL", f)
    breaches = gate(m)
    if a.gate:
        print("QUALITY GATE " + ("FAILED: " + "; ".join(breaches) if breaches else "PASSED"))
        sys.exit(1 if breaches else 0)


if __name__ == "__main__":
    main()
