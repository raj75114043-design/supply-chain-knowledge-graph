"""Supply-chain risk console (Streamlit)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import streamlit as st  # noqa: E402

try:
    for key in ("GROQ_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        if key in st.secrets:
            os.environ[key] = str(st.secrets[key])
except Exception:
    pass

import pandas as pd  # noqa: E402

from sckg import analytics as A  # noqa: E402
from sckg.config import get_settings  # noqa: E402
from sckg.llm import build_llm  # noqa: E402
from sckg.pipeline import get_build  # noqa: E402
from sckg.qa import QA  # noqa: E402

logging.disable(logging.INFO)
st.set_page_config(page_title="Supply-Chain Knowledge Graph", page_icon="🕸️", layout="wide")
b = get_build()
kg = b.kg
qa = QA(kg, build_llm(get_settings()))
COLORS = {"Product": "#FF3B3B", "Assembly": "#E76F51", "Part": "#F4A261", "Supplier": "#264653", "Company": "#6D597A", "City": "#2A9D8F",
          "Region": "#8AB17D", "Event": "#B5179E", "SanctionsEntry": "#000000"}


def dot(nodes: set[str], highlight: set[str] = frozenset()) -> str:
    lines = ['digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fontname=Helvetica, fontsize=10, fontcolor=white];']
    for n in nodes:
        k = kg.kind(n)
        tier = kg.g.nodes[n].get("tier")
        label = kg.name(n).replace('"', "'")[:32] + (f"\\n(tier {tier})" if k == "Supplier" else f"\\n{k}")
        hl = n in highlight
        lines.append(f'"{n}" [label="{label}", fillcolor="{COLORS.get(k, "#999")}", penwidth={3 if hl else 1}, color="{"#FFD60A" if hl else "#fff"}"];')
    for u, v, k in kg.g.edges(keys=True):
        if u in nodes and v in nodes and k != "IN_REGION":
            lines.append(f'"{u}" -> "{v}" [label="{k}", fontsize=7];')
    return "\n".join(lines + ["}"])


def impact_nodes(r: dict, event: str | None = None) -> set[str]:
    nodes = set(r["disrupted"]) | {s for path in r["tier1_affected"].values() for s in path}
    for p in r["parts"]:
        nodes.add(p["part"])
    for prod in r["products"]:
        nodes.add(prod["product"])
        nodes |= {a for a, _ in kg.out(prod["product"], "HAS_ASSEMBLY") if any(pt in nodes for pt, _ in kg.out(a, "HAS_PART"))}
    if event:
        nodes.add(event)
        nodes |= {t for t, _ in kg.out(event, "AFFECTS")}
    return nodes


with st.sidebar:
    st.markdown("### 🕸️ Supply-Chain Knowledge Graph")
    st.caption("Helix Motors (fictional EV maker) · ERP + supplier documents + sanctions list")
    s = b.stats
    st.markdown(f"**Graph:** {s['nodes']} nodes · {s['edges']} edges  \n**Documents:** {s['documents']} → {s['triples']} extracted facts  \n"
                f"**Companies found only in documents:** {s['entities_from_documents']}  \n**Entity review queue:** {s['review_queue']}  \n"
                f"**Build time:** {s['build_ms']} ms")
    st.divider()
    st.markdown("**Try asking**")
    for q in ["What is the impact of the Kyushu earthquake?", "Are we exposed to any sanctioned companies?", "Who supplies the lithium-ion cells?",
              "Do we have hidden sub-tier concentration?", "What happens if we lose Formosa Wafer?", "Which parts are single-sourced?"]:
        if st.button(q, width="stretch"):
            st.session_state["q"] = q

tabs = st.tabs(["💬 Ask the graph", "🌪️ Risk events", "🔎 Supplier explorer", "🧭 Concentration & sanctions", "🧩 Pipeline", "🧪 Evaluation", "🏗️ Architecture"])

with tabs[0]:
    q = st.text_input("Question", key="q", placeholder="What is the impact of the Kyushu earthquake?")
    if q:
        r = qa.ask(q)
        st.markdown(r["answer"])
        st.caption(f"intent: {r['intent']} · linked: {', '.join(f'{k}={v}' for k, v in r['linked'].items() if v) or '—'} · writer: {r['mode']}")
        for path in r["evidence"]:
            if path:
                st.markdown("**Evidence path** (each hop with its source)")
                st.dataframe(pd.DataFrame(path), hide_index=True, width="stretch")
        if r["linked"]["event"]:
            st.graphviz_chart(dot(impact_nodes(A.event_impact(kg, r["linked"]["event"]), r["linked"]["event"])))
        elif r["linked"]["supplier"] and r["intent"] == "supplier_impact":
            st.graphviz_chart(dot(impact_nodes(A.stress_test(kg, r["linked"]["supplier"])), {r["linked"]["supplier"]}))

with tabs[1]:
    rows = []
    for e in kg.nodes_of("Event"):
        r = A.event_impact(kg, e)
        rows.append({"event": kg.name(e), "id": e, "weeks": r["weeks"], "tier-1 hit": len(r["tier1_affected"]),
                     "via sub-tier only": ", ".join(kg.name(x) for x in r["sub_tier_only"]), "revenue at risk ($M)": r["revenue_at_risk_musd"]})
    df = pd.DataFrame(rows).sort_values("revenue at risk ($M)", ascending=False)
    st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
    pick = st.selectbox("Event", df["id"], format_func=kg.name)
    r = A.event_impact(kg, pick)
    st.dataframe(pd.DataFrame(r["products"]), hide_index=True, width="stretch")
    st.dataframe(pd.DataFrame(r["parts"]).drop(columns=["via"]), hide_index=True, width="stretch")
    st.graphviz_chart(dot(impact_nodes(r, pick)))

with tabs[2]:
    name = st.text_input("Company name as it appears anywhere (try 'VCS', 'GREM', 'Penang Precision Tooling')", "GREM")
    cands = b.resolver.candidates(name, 4)
    st.dataframe(pd.DataFrame([{"entity": c, "name": b.resolver.entities[c].name, "score": s, "source": b.resolver.entities[c].source}
                               for c, s in cands]), hide_index=True, width="stretch")
    sup = cands[0][0] if cands and cands[0][1] >= 0.86 and cands[0][0] in kg.g else None
    if sup:
        n = kg.g.nodes[sup]
        st.markdown(f"**{n['name']}** · tier {n.get('tier')} · aliases seen: {', '.join(n.get('aliases', [])) or '—'}")
        st.json({"supplies": [kg.name(v) for v, _ in kg.out(sup, "SUPPLIES")], "fed_by": [kg.name(u) for u, _ in kg.into(sup, "SUPPLIES")],
                 "parts": [kg.name(p) for p, _ in kg.into(sup, "SOURCED_FROM")], "owned_by": [kg.name(v) for v, _ in kg.out(sup, "SUBSIDIARY_OF")]})
        st.markdown(f"**Stress test:** losing it for its recovery time puts **${A.stress_test(kg, sup)['revenue_at_risk_musd']}M** at risk.")
    st.markdown("**Supplier criticality**")
    st.dataframe(pd.DataFrame(A.criticality(kg)), hide_index=True, width="stretch")

with tabs[3]:
    st.markdown("**Hidden sub-tier concentration** (invisible in the ERP, found in documents)")
    st.dataframe(pd.DataFrame(A.hidden_concentration(kg)), hide_index=True, width="stretch")
    st.markdown("**Sanctions exposure**")
    st.dataframe(pd.DataFrame(A.sanctions_exposure(kg)), hide_index=True, width="stretch")
    st.markdown("**Single-source parts**")
    st.dataframe(pd.DataFrame(A.single_source_parts(kg)), hide_index=True, width="stretch")

with tabs[4]:
    docs = {d["doc_id"]: d for d in b.raw["documents"]}
    did = st.selectbox("Document", list(docs), format_func=lambda d: f"{d} · {docs[d]['type']} · {docs[d]['title']}")
    st.info(docs[did]["text"])
    tr = [t.as_dict() for t in b.triples if t.doc_id == did]
    for t in tr:
        t["head_resolved"] = b.resolution.get(t["head"], (t["head"], None))[0]
        t["tail_resolved"] = b.resolution.get(t["tail"], (t["tail"], None))[0]
    st.dataframe(pd.DataFrame(tr)[["relation", "head", "head_resolved", "tail", "tail_resolved", "extractor", "confidence"]] if tr else pd.DataFrame(),
                 hide_index=True, width="stretch")
    st.markdown("**Entities created from documents** (not in the ERP)")
    st.dataframe(pd.DataFrame([{"id": e.entity_id, "canonical": e.name, "surface forms": ", ".join(sorted(e.names))}
                               for e in b.resolver.entities.values() if e.source == "documents"]), hide_index=True, width="stretch")
    st.markdown("**Entity-resolution review queue** (ambiguous names are not guessed)")
    st.json(b.resolver.review_queue or [])

with tabs[5]:
    if st.button("Run evaluation", type="primary"):
        from sckg.eval.run import evaluate, gate
        m = evaluate()
        c = st.columns(4)
        for col, k in zip(c * 2, ["extraction_precision", "extraction_recall", "extraction_recall_unseen", "er_bcubed_f1", "event_products_match",
                                   "concentration_match", "sanctions_match", "qa_accuracy"], strict=False):
            col.metric(k.replace("_", " "), f"{m[k]:.0%}")
        st.dataframe(pd.DataFrame(m["events"]), hide_index=True, width="stretch")
        br = gate(m)
        (st.error if br else st.success)("Quality gate " + ("FAILED: " + "; ".join(br) if br else "PASSED"))

with tabs[6]:
    st.graphviz_chart("""
    digraph P { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#f4f4f4", fontname=Helvetica];
      E [label="ERP\\nBOM · sourcing · tier-1"]; D [label="Supplier documents\\naudits · disclosures · alerts"]; S [label="Sanctions list"];
      X [label="Extraction\\npatterns + co-occurrence\\n(+ optional LLM)"]; R [label="Entity resolution\\nacronyms · prefixes · fuzzy\\nreview queue"];
      G [label="Knowledge graph\\nprovenance on every edge"]; N [label="Neo4j mirror"]; A [label="Analytics\\nimpact · stress · concentration\\nsanctions · criticality"];
      Q [label="GraphRAG Q&A"];
      D -> X -> R -> G; E -> G; S -> R; G -> A -> Q; G -> N; }""")
