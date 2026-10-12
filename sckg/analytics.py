"""Supply-chain risk analytics on the knowledge graph.

Impact model (per disrupted tier-1 supplier, duration D weeks):
  part loss share  = sum of sourcing shares of disrupted suppliers for that part
  weeks lost       = max(0, D − inventory weeks of the part)            (time-to-recover vs time-to-survive)
  product loss     = max over its parts of (loss share × weeks lost)    (a vehicle needs every part)
  revenue at risk  = weekly revenue × product loss
A tier-1 supplier is disrupted directly (located in the affected area, or named) or **through its sub-tier**
(an upstream supplier found in documents is disrupted). Explanations are graph paths with provenance.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from sckg.graph import KG


def _located(kg: KG, supplier: str) -> tuple[str | None, str | None]:
    for c, _ in kg.out(supplier, "LOCATED_IN"):
        reg = next((r for r, _ in kg.out(c, "IN_REGION")), None)
        return c, reg
    return None, None


def upstream(kg: KG, supplier: str, depth: int = 3) -> list[list[str]]:
    """Paths of sub-tier suppliers feeding `supplier` (each path ends at an upstream company)."""
    paths, frontier = [], [[supplier]]
    for _ in range(depth):
        nxt = []
        for p in frontier:
            for u, _ in kg.into(p[-1], "SUPPLIES"):
                if u not in p:
                    nxt.append(p + [u])
        paths += nxt
        frontier = nxt
    return paths


def products_of_part(kg: KG, part: str) -> list[str]:
    return sorted({p for a, _ in kg.into(part, "HAS_PART") for p, _ in kg.into(a, "HAS_ASSEMBLY")})


def directly_disrupted(kg: KG, event: str) -> set[str]:
    hit = set()
    for target, _ in kg.out(event, "AFFECTS"):
        kind = kg.kind(target)
        if kind == "Supplier":
            hit.add(target)
        for s in kg.nodes_of("Supplier"):
            c, r = _located(kg, s)
            if target in (c, r):
                hit.add(s)
    return hit


def impact(kg: KG, disrupted: set[str], weeks: float, label: str = "") -> dict:
    tier1 = {}   # tier-1 supplier → explanation path
    for s in kg.nodes_of("Supplier"):
        if kg.g.nodes[s].get("tier") != 1:
            continue
        if s in disrupted:
            tier1[s] = [s]
            continue
        for path in upstream(kg, s):
            if path[-1] in disrupted:
                tier1[s] = path
                break
    parts = {}
    for part in kg.nodes_of("Part"):
        src = kg.out(part, "SOURCED_FROM")
        share = sum(d["share"] for s, d in src if s in tier1)
        if share <= 0:
            continue
        inv = kg.g.nodes[part]["inventory_weeks"]
        parts[part] = {"part": part, "name": kg.name(part), "share_lost": round(share, 2), "inventory_weeks": inv,
                       "weeks_lost": max(0.0, weeks - inv), "via": {s: tier1[s] for s, _ in src if s in tier1},
                       "single_source": len(src) == 1}
    products = []
    for p in kg.nodes_of("Product"):
        worst = [(parts[pt]["share_lost"] * parts[pt]["weeks_lost"], pt) for pt in parts if p in products_of_part(kg, pt)]
        if not worst:
            continue
        loss, pt = max(worst)
        rev = kg.g.nodes[p]["weekly_revenue_musd"]
        products.append({"product": p, "name": kg.name(p), "loss_weeks": round(loss, 2), "revenue_at_risk_musd": round(rev * loss, 1),
                         "binding_part": pt, "exposed_parts": sorted(pt for _, pt in worst)})
    products.sort(key=lambda x: -x["revenue_at_risk_musd"])
    return {"label": label, "weeks": weeks, "disrupted": sorted(disrupted), "tier1_affected": tier1,
            "sub_tier_only": sorted(s for s, path in tier1.items() if len(path) > 1), "parts": sorted(parts.values(), key=lambda x: x["part"]),
            "products": products, "revenue_at_risk_musd": round(sum(x["revenue_at_risk_musd"] for x in products), 1)}


def event_impact(kg: KG, event: str) -> dict:
    d = kg.g.nodes[event]
    return impact(kg, directly_disrupted(kg, event), d["weeks"], f"{d['event_type']} ({d.get('date', '')})")


def stress_test(kg: KG, supplier: str) -> dict:
    """Lose a supplier for its time-to-recover (tier-1: from sourcing; sub-tier: longest TTR of its customers)."""
    ttr = [d["ttr_weeks"] for _, d in kg.into(supplier, "SOURCED_FROM")]
    if not ttr:
        customers = {c for path in _downstream(kg, supplier) for c in path}
        ttr = [d["ttr_weeks"] for c in customers for _, d in kg.into(c, "SOURCED_FROM")] or [4]
    return impact(kg, {supplier}, max(ttr), f"loss of {kg.name(supplier)}")


def _downstream(kg: KG, supplier: str) -> list[list[str]]:
    paths, frontier = [], [[supplier]]
    for _ in range(3):
        nxt = [p + [v] for p in frontier for v, _ in kg.out(p[-1], "SUPPLIES") if v not in p]
        paths += nxt
        frontier = nxt
    return paths


def single_source_parts(kg: KG) -> list[dict]:
    out = []
    for part in kg.nodes_of("Part"):
        src = kg.out(part, "SOURCED_FROM")
        if len(src) == 1:
            out.append({"part": part, "name": kg.name(part), "supplier": src[0][0], "supplier_name": kg.name(src[0][0]),
                        "inventory_weeks": kg.g.nodes[part]["inventory_weeks"], "ttr_weeks": src[0][1]["ttr_weeks"]})
    return out


def hidden_concentration(kg: KG) -> list[dict]:
    """Sub-tier companies feeding several tier-1 suppliers, and dual-sourced parts whose sources share an upstream."""
    out = []
    for s in kg.nodes_of("Supplier"):
        if kg.g.nodes[s].get("tier") == 1:
            continue
        customers = sorted({p[-1] for p in _downstream(kg, s) if kg.g.nodes[p[-1]].get("tier") == 1})
        if len(customers) < 2:
            continue
        parts = sorted({part for c in customers for part, _ in kg.into(c, "SOURCED_FROM")})
        false_dual = [pt for pt in parts if len(kg.out(pt, "SOURCED_FROM")) > 1 and all(src in customers for src, _ in kg.out(pt, "SOURCED_FROM"))]
        products = sorted({p for pt in parts for p in products_of_part(kg, pt)})
        out.append({"company": s, "name": kg.name(s), "tier1_customers": customers, "parts": parts, "false_dual_sourcing": false_dual,
                    "products": products})
    return sorted(out, key=lambda x: (-len(x["tier1_customers"]), x["company"]))


def sanctions_exposure(kg: KG) -> list[dict]:
    out = []
    for entry in kg.nodes_of("SanctionsEntry"):
        for matched, d in kg.into(entry, "SANCTIONS_MATCH"):
            owned = [c for c, _ in kg.into(matched, "SUBSIDIARY_OF")] + [matched]
            for company in owned:
                tier1 = {p[-1] for p in _downstream(kg, company)} | ({company} if kg.g.nodes[company].get("tier") == 1 else set())
                for t1 in sorted(x for x in tier1 if kg.g.nodes[x].get("tier") == 1):
                    parts = [pt for pt, _ in kg.into(t1, "SOURCED_FROM")]
                    out.append({"sanctions_entry": entry, "listed_name": kg.name(entry), "matched_entity": matched, "via_company": company,
                                "via_name": kg.name(company), "tier1_supplier": t1, "parts": parts,
                                "products": sorted({p for pt in parts for p in products_of_part(kg, pt)}), "match_score": d["score"]})
    return out


def criticality(kg: KG) -> list[dict]:
    simple = nx.Graph()
    simple.add_edges_from((u, v) for u, v, k in kg.g.edges(keys=True) if k in ("HAS_ASSEMBLY", "HAS_PART", "SOURCED_FROM", "SUPPLIES"))
    btw = nx.betweenness_centrality(simple)
    rows = []
    for s in kg.nodes_of("Supplier"):
        st = stress_test(kg, s)
        rows.append({"supplier": s, "name": kg.name(s), "tier": kg.g.nodes[s].get("tier"), "revenue_at_risk_musd": st["revenue_at_risk_musd"],
                     "products_exposed": len(st["products"]), "betweenness": round(btw.get(s, 0.0), 3)})
    return sorted(rows, key=lambda r: -r["revenue_at_risk_musd"])


def explain_path(kg: KG, src: str, dst: str) -> list[dict]:
    """Shortest explanation path with the provenance of each hop."""
    und = kg.g.to_undirected(as_view=True)
    try:
        nodes = nx.shortest_path(und, src, dst)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    hops = []
    for a, b in zip(nodes, nodes[1:], strict=False):
        data = kg.g.get_edge_data(a, b) or kg.g.get_edge_data(b, a) or {}
        rel, d = next(iter(data.items())) if data else ("?", {})
        hops.append({"from": kg.name(a), "rel": rel, "to": kg.name(b),
                     "source": ", ".join(sorted({p.get("doc_id", p.get("source")) for p in d.get("provenance", [])}))})
    return hops


def by_event_type(kg: KG) -> dict[str, str]:
    return {e: kg.g.nodes[e]["event_type"] for e in kg.nodes_of("Event")}


def summary(kg: KG) -> dict:
    events = {e: event_impact(kg, e) for e in kg.nodes_of("Event")}
    return {"events": events, "single_source": single_source_parts(kg), "concentration": hidden_concentration(kg),
            "sanctions": sanctions_exposure(kg), "counts": defaultdict(int)}
