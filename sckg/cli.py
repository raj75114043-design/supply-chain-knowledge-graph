"""Command line: build, ask, export, and load into Neo4j.

    python -m sckg.cli build                 # run the pipeline, print statistics, write data/graph.json
    python -m sckg.cli ask "What is the impact of the Kyushu earthquake?"
    python -m sckg.cli neo4j-check           # load into Neo4j (NEO4J_* env) and compare Cypher with Python analytics
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from sckg import analytics as A
from sckg.config import ROOT, get_settings
from sckg.pipeline import get_build
from sckg.qa import QA


def main() -> None:
    logging.disable(logging.INFO)
    ap = argparse.ArgumentParser(prog="sckg")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    q = sub.add_parser("ask")
    q.add_argument("question")
    sub.add_parser("neo4j-check")
    a = ap.parse_args()
    b = get_build()
    if a.cmd == "build":
        (ROOT / "data" / "graph.json").write_text(json.dumps(b.kg.to_records(), indent=1, default=str))
        print(json.dumps(b.stats, indent=2))
    elif a.cmd == "ask":
        r = QA(b.kg).ask(a.question)
        print(r["answer"])
        for path in r["evidence"]:
            print("  path:", " → ".join(f"{h['from']} -[{h['rel']}]-> {h['to']} ({h['source']})" for h in path))
    else:
        from sckg.neo4j_store import Neo4jMirror
        s = get_settings()
        mirror = Neo4jMirror(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
        print("loaded", mirror.load(b.kg))
        bad = []
        for e in b.kg.nodes_of("Event"):
            py = sorted({p["product"] for p in A.event_impact(b.kg, e)["products"]})
            cy = mirror.impacted_products(e)
            print(e, "python", py, "cypher", cy)
            if py != cy:
                bad.append(e)
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
