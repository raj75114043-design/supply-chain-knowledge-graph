"""Knowledge-graph construction.

Ontology
  (Product)-[:HAS_ASSEMBLY]->(Assembly)-[:HAS_PART]->(Part)-[:SOURCED_FROM {share, ttr_weeks}]->(Supplier)
  (Supplier)-[:SUPPLIES {component}]->(Supplier)          sub-tier, from documents
  (Supplier)-[:SUBSIDIARY_OF]->(Company)                   ownership, from documents
  (Supplier)-[:LOCATED_IN]->(City)-[:IN_REGION]->(Region)
  (Event)-[:AFFECTS {weeks}]->(Region | City | Supplier)    risk alerts
  (Company)-[:SANCTIONS_MATCH {score}]->(SanctionsEntry)   screening
Every edge carries provenance: source ("erp" or a document id), the sentence, extractor and confidence.
"""
from __future__ import annotations

import networkx as nx

RELATIONS = ["HAS_ASSEMBLY", "HAS_PART", "SOURCED_FROM", "SUPPLIES", "SUBSIDIARY_OF", "LOCATED_IN", "IN_REGION", "AFFECTS", "SANCTIONS_MATCH"]


def city(name: str) -> str:
    return f"city:{name}"


def region(name: str) -> str:
    return f"region:{name}"


class KG:
    def __init__(self):
        self.g = nx.MultiDiGraph()

    def node(self, nid: str, kind: str, **attrs):
        if nid in self.g:
            self.g.nodes[nid].update({k: v for k, v in attrs.items() if v is not None})
        else:
            self.g.add_node(nid, kind=kind, **attrs)

    def edge(self, u: str, v: str, rel: str, provenance: dict, **attrs):
        if self.g.has_edge(u, v, key=rel):
            data = self.g.edges[u, v, rel]
            data["provenance"].append(provenance)
            data["confidence"] = max(data["confidence"], provenance.get("confidence", 1.0))
            data.update({k: val for k, val in attrs.items() if val is not None and k not in data})
        else:
            self.g.add_edge(u, v, key=rel, rel=rel, provenance=[provenance], confidence=provenance.get("confidence", 1.0), **attrs)

    # ------------------------------------------------------------------ queries used by analytics and QA
    def kind(self, n):
        return self.g.nodes[n].get("kind")

    def name(self, n):
        return self.g.nodes[n].get("name", n)

    def out(self, n, rel):
        return [(v, d) for _, v, k, d in self.g.out_edges(n, keys=True, data=True) if k == rel]

    def into(self, n, rel):
        return [(u, d) for u, _, k, d in self.g.in_edges(n, keys=True, data=True) if k == rel]

    def nodes_of(self, kind):
        return [n for n, d in self.g.nodes(data=True) if d.get("kind") == kind]

    def stats(self) -> dict:
        kinds, rels = {}, {}
        for _, d in self.g.nodes(data=True):
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
        for _, _, k in self.g.edges(keys=True):
            rels[k] = rels.get(k, 0) + 1
        return {"nodes": self.g.number_of_nodes(), "edges": self.g.number_of_edges(), "node_kinds": kinds, "relations": rels}

    def to_records(self) -> dict:
        return {"nodes": [{"id": n, **d} for n, d in self.g.nodes(data=True)],
                "edges": [{"source": u, "target": v, "rel": k, **{x: y for x, y in d.items() if x != "rel"}}
                          for u, v, k, d in self.g.edges(keys=True, data=True)]}


def build(erp: dict, regions: list[dict], facts: list[dict], entities: dict[str, dict], sanctions_matches: list[dict] | None = None) -> KG:
    """`facts`: resolved relations {head, relation, tail, attrs, provenance}; `entities`: id → {name, tier, source}."""
    kg = KG()
    erp_prov = {"source": "erp", "extractor": "erp", "confidence": 1.0}
    for r in regions:
        kg.node(city(r["city"]), "City", name=r["city"], country=r["country"])
        kg.node(region(r["region"]), "Region", name=r["region"], country=r["country"])
        kg.edge(city(r["city"]), region(r["region"]), "IN_REGION", erp_prov)
    for p in erp["products"]:
        kg.node(p["product_id"], "Product", name=p["name"], weekly_revenue_musd=p["weekly_revenue_musd"])
    for a in erp["assemblies"]:
        kg.node(a["assembly_id"], "Assembly", name=a["name"])
    for p in erp["parts"]:
        kg.node(p["part_id"], "Part", name=p["name"], inventory_weeks=p["inventory_weeks"])
    for b in erp["bom"]:
        kg.edge(b["parent"], b["child"], "HAS_ASSEMBLY" if b["child"].startswith("A-") else "HAS_PART", erp_prov)
    for s in erp["suppliers"]:
        kg.node(s["supplier_id"], "Supplier", name=s["legal_name"], tier=1, source="erp", country=s["country"])
        kg.edge(s["supplier_id"], city(s["site_city"]), "LOCATED_IN", erp_prov)
    for s in erp["sourcing"]:
        kg.edge(s["part_id"], s["supplier_id"], "SOURCED_FROM", erp_prov, share=s["share"], ttr_weeks=s["ttr_weeks"])
    for eid, e in entities.items():
        if eid not in kg.g:
            kg.node(eid, "Supplier" if e.get("tier") in (1, 2) else "Company", name=e["name"], tier=e.get("tier"), source=e.get("source", "documents"),
                    aliases=sorted(e.get("names", [])))
    for f in facts:
        h, rel, t, attrs, prov = f["head"], f["relation"], f["tail"], f.get("attrs", {}), f["provenance"]
        if rel == "SUPPLIES":
            kg.edge(h, t, rel, prov, component=attrs.get("component"))
            if kg.g.nodes[h].get("tier") is None:
                kg.g.nodes[h]["tier"], kg.g.nodes[h]["kind"] = 2, "Supplier"
        elif rel == "SUBSIDIARY_OF":
            kg.node(t, "Company")
            kg.edge(h, t, rel, prov)
        elif rel == "LOCATED_IN":
            kg.edge(h, city(t), rel, prov)
        elif rel == "AFFECTS":
            kg.node(h, "Event", name=f"{attrs['event_type']} ({attrs.get('date', '')})", event_type=attrs["event_type"],
                    weeks=attrs["weeks"], date=attrs.get("date"))
            target = t if attrs.get("target_kind") == "supplier" else (region(t) if region(t) in kg.g else city(t))
            kg.edge(h, target, rel, prov, weeks=attrs["weeks"])
    for m in sanctions_matches or []:
        kg.node(m["list_id"], "SanctionsEntry", name=m["list_name"], program=m["program"])
        kg.edge(m["entity_id"], m["list_id"], "SANCTIONS_MATCH", {"source": "sanctions_list", "extractor": "screening", "confidence": m["score"]},
                score=m["score"])
    return kg
