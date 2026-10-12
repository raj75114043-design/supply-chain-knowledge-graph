"""Mirror the knowledge graph into Neo4j and run the key analytics in Cypher.

The NetworkX graph is the system of record for the pipeline; Neo4j serves exploration (Bloom / Browser) and other teams'
queries. The integration test checks that Cypher returns the same affected products as the Python analytics.
"""
from __future__ import annotations

import json

from sckg.graph import KG

LABELS = {"Product", "Assembly", "Part", "Supplier", "Company", "City", "Region", "Event", "SanctionsEntry"}

IMPACTED_PRODUCTS = """
MATCH (e:Event {id: $event})-[:AFFECTS]->(t)
OPTIONAL MATCH (t)<-[:IN_REGION]-(c:City)
WITH e, collect(DISTINCT t) + collect(DISTINCT c) AS places
MATCH (s:Supplier)
WHERE s IN places OR EXISTS { MATCH (s)-[:LOCATED_IN]->(x) WHERE x IN places }
MATCH (t1:Supplier {tier: 1})
WHERE t1 = s OR EXISTS { MATCH (s)-[:SUPPLIES*1..3]->(t1) }
MATCH (p:Product)-[:HAS_ASSEMBLY]->(:Assembly)-[:HAS_PART]->(pt:Part)-[:SOURCED_FROM]->(t1)
RETURN DISTINCT p.id AS product ORDER BY product
"""


class Neo4jMirror:  # pragma: no cover - exercised by the integration job
    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def load(self, kg: KG) -> dict:
        recs = kg.to_records()
        with self.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
            for label in LABELS:
                s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
                rows = [{"id": n["id"], **{k: v for k, v in n.items() if k not in ("id", "kind") and isinstance(v, (str, int, float, bool))}}
                        for n in recs["nodes"] if n["kind"] == label]
                if rows:
                    s.run(f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n += r", rows=rows)
            by_rel: dict[str, list] = {}
            for e in recs["edges"]:
                props = {k: v for k, v in e.items() if k not in ("source", "target", "rel", "provenance") and isinstance(v, (str, int, float, bool))}
                props["provenance"] = json.dumps(e["provenance"], default=str)
                by_rel.setdefault(e["rel"], []).append({"s": e["source"], "t": e["target"], "p": props})
            for rel, rows in by_rel.items():
                s.run(f"UNWIND $rows AS r MATCH (a {{id: r.s}}), (b {{id: r.t}}) MERGE (a)-[x:{rel}]->(b) SET x += r.p", rows=rows)
            n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            m = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return {"nodes": n, "edges": m}

    def impacted_products(self, event_id: str) -> list[str]:
        with self.driver.session() as s:
            return [r["product"] for r in s.run(IMPACTED_PRODUCTS, event=event_id)]
