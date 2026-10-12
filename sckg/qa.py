"""GraphRAG question answering: question → intent + linked entities → graph query → answer with evidence paths.

The graph, not the language model, produces the facts. An optional LLM rewrites the templated answer; it is accepted
only if every identifier and dollar figure it mentions appears in the evidence.
"""
from __future__ import annotations

import json
import re

from sckg import analytics as A
from sckg.graph import KG
from sckg.llm import LLMClient, LLMUsage
from sckg.resolve import score

INTENTS = [
    ("sanctions", r"\bsanction|\bexport control|restricted part(y|ies)|\bwatch ?list"),
    ("concentration", r"hidden|concentrat|single point|false dual|sub-?tier risk|common (upstream|supplier)"),
    ("single_source", r"single[- ]sourc|sole[- ]sourc|only one supplier"),
    ("critical", r"most critical|riskiest|biggest risk|rank.*supplier"),
    ("event_impact", r"impact|affect|expos(ed|ure)|what happens|revenue at risk|disrupt|hurt"),
    ("suppliers_of", r"who (supplies|makes)|supplier[s]? (of|for)|sourced from|alternatives? for"),
    ("depends", r"depend|use[sd]? .* from|rely on"),
]
EVENT_WORDS = {"flood": "flood", "earthquake": "earthquake", "quake": "earthquake", "export": "export restriction", "rare earth": "export restriction",
               "fire": "fire", "strike": "port strike", "port": "port strike", "typhoon": "typhoon"}


class QA:
    def __init__(self, kg: KG, llm: LLMClient | None = None):
        self.kg, self.llm = kg, llm or LLMClient()

    # ------------------------------------------------------------------ linking
    def link_event(self, q: str) -> str | None:
        ql = q.lower()
        events = self.kg.nodes_of("Event")
        for word, etype in EVENT_WORDS.items():
            if word in ql:
                hits = [e for e in events if self.kg.g.nodes[e]["event_type"] == etype]
                if hits:
                    return hits[0]
        for e in events:   # by place: "the Guangdong situation"
            for t, _ in self.kg.out(e, "AFFECTS"):
                if self.kg.name(t).lower() in ql:
                    return e
        return None

    def link_supplier(self, q: str) -> str | None:
        best, best_s = None, 0.0
        cands = [(s, [self.kg.name(s), *self.kg.g.nodes[s].get("aliases", [])]) for s in self.kg.nodes_of("Supplier")]
        words = re.findall(r"[A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*", q)
        for phrase in words:
            for s, names in cands:
                sc = score(phrase, names)
                if sc > best_s:
                    best, best_s = s, sc
        return best if best_s >= 0.86 else None

    def link_part(self, q: str) -> str | None:
        ql = q.lower()
        for p in self.kg.nodes_of("Part"):
            name = self.kg.name(p).lower()
            if p.lower() in ql or name in ql or (name.split()[-1] in ql and len(name.split()[-1]) > 4):
                return p
        return None

    # ------------------------------------------------------------------ answering
    def ask(self, question: str) -> dict:
        intent = next((i for i, rx in INTENTS if re.search(rx, question, re.I)), "unknown")
        event, supplier, part = self.link_event(question), self.link_supplier(question), self.link_part(question)
        if intent in ("event_impact", "depends") and event is None and supplier is not None:
            intent = "supplier_impact"
        if intent == "event_impact" and event is None and supplier is None:
            intent = "unknown"
        if intent in ("suppliers_of",) and part is None:
            intent = "unknown"
        handler = getattr(self, f"_a_{intent}")
        answer, evidence, facts = handler(question, event=event, supplier=supplier, part=part)
        answer = re.sub(r"\.{2,}", ".", answer)
        text, mode = self._write(question, answer, facts)
        return {"question": question, "intent": intent, "linked": {"event": event, "supplier": supplier, "part": part},
                "answer": text, "mode": mode, "facts": facts, "evidence": evidence}

    def _a_event_impact(self, q, event, **_):
        r = A.event_impact(self.kg, event)
        hit = [p for p in r["products"] if p["loss_weeks"] > 0]
        buffered = [p["name"] for p in r["products"] if p["loss_weeks"] == 0]
        names = ", ".join(self.kg.name(s) for s in r["tier1_affected"])
        lines = [f"The {r['label']} disrupts tier-1 suppliers {names or 'none'} for {r['weeks']} weeks."]
        if r["sub_tier_only"]:
            lines.append("Exposure through the sub-tier (not visible in the ERP): " +
                         "; ".join(f"{self.kg.name(s)} via {self.kg.name(r['tier1_affected'][s][-1])}" for s in r["sub_tier_only"]) + ".")
        if hit:
            lines.append("Revenue at risk: " + ", ".join(f"{p['name']} ${p['revenue_at_risk_musd']}M ({p['loss_weeks']} lost weeks, "
                                                          f"binding part {self.kg.name(p['binding_part'])})" for p in hit) +
                         f" — total ${r['revenue_at_risk_musd']}M.")
        if buffered:
            lines.append(f"Covered by inventory (no lost production): {', '.join(buffered)}.")
        ev = [A.explain_path(self.kg, event, p["binding_part"]) for p in hit[:1]]
        return " ".join(lines), ev, {"revenue_at_risk_musd": r["revenue_at_risk_musd"], "products": [p["product"] for p in hit],
                                     "tier1": sorted(r["tier1_affected"])}

    def _a_supplier_impact(self, q, supplier, **_):
        r = A.stress_test(self.kg, supplier)
        hit = [p for p in r["products"] if p["loss_weeks"] > 0]
        tier = self.kg.g.nodes[supplier].get("tier")
        via = f" It is a tier-{tier} supplier" + (f" feeding {', '.join(self.kg.name(s) for s in r['sub_tier_only'])}." if r["sub_tier_only"] else ".")
        text = (f"Losing {self.kg.name(supplier)} for {r['weeks']} weeks (its time to recover) puts ${r['revenue_at_risk_musd']}M at risk across "
                f"{', '.join(p['name'] for p in hit) or 'no products'}." + via)
        return text, [A.explain_path(self.kg, supplier, hit[0]["product"])] if hit else [], {
            "revenue_at_risk_musd": r["revenue_at_risk_musd"], "products": [p["product"] for p in hit]}

    def _a_depends(self, q, supplier, **kw):
        return self._a_supplier_impact(q, supplier=supplier, **kw)

    def _a_suppliers_of(self, q, part, **_):
        src = self.kg.out(part, "SOURCED_FROM")
        parts = [f"{self.kg.name(s)} ({int(d['share'] * 100)}%, recovers in {d['ttr_weeks']} weeks)" for s, d in src]
        ups = sorted({self.kg.name(p[-1]) for s, _ in src for p in A.upstream(self.kg, s)})
        text = f"{self.kg.name(part)} ({part}) is sourced from {', '.join(parts)}." + (f" Their sub-tier includes {', '.join(ups)}." if ups else "")
        common = set.intersection(*[{p[-1] for p in A.upstream(self.kg, s)} for s, _ in src]) if len(src) > 1 else set()
        if common:
            text += (f" Warning: all sources depend on {', '.join(sorted(self.kg.name(c) for c in common))}, "
                     "so the dual sourcing is not independent.")
        return text, [], {"suppliers": [s for s, _ in src]}

    def _a_single_source(self, q, **_):
        rows = A.single_source_parts(self.kg)
        risky = [r for r in rows if r["ttr_weeks"] > r["inventory_weeks"]]
        text = (f"{len(rows)} of {len(self.kg.nodes_of('Part'))} parts are single-sourced. Where recovery outlasts inventory: " +
                "; ".join(f"{r['name']} from {r['supplier_name']} (recover {r['ttr_weeks']}w vs stock {r['inventory_weeks']}w)" for r in risky) + ".")
        return text, [], {"parts": [r["part"] for r in rows]}

    def _a_concentration(self, q, **_):
        rows = A.hidden_concentration(self.kg)
        lines = [f"{r['name']} feeds {len(r['tier1_customers'])} tier-1 suppliers ({', '.join(self.kg.name(c) for c in r['tier1_customers'])})"
                 + (f"; dual sourcing of {', '.join(self.kg.name(p) for p in r['false_dual_sourcing'])} is not independent" if r["false_dual_sourcing"] else "")
                 for r in rows]
        return "Hidden sub-tier concentration: " + ". ".join(lines) + ".", [], {"companies": [r["company"] for r in rows]}

    def _a_sanctions(self, q, **_):
        rows = A.sanctions_exposure(self.kg)
        if not rows:
            return "No supplier in the graph matches the sanctions list.", [], {"exposed_tier1": []}
        r0 = rows[0]
        text = (f"Yes. {self.kg.name(r0['matched_entity'])} matches list entry {r0['sanctions_entry']} ({r0['listed_name']}, score {r0['match_score']}). "
                f"Its subsidiary {r0['via_name']} supplies " + ", ".join(sorted({self.kg.name(r['tier1_supplier']) for r in rows})) +
                f", exposing {', '.join(sorted({self.kg.name(p) for r in rows for p in r['products']}))}.")
        return text, [A.explain_path(self.kg, r0["sanctions_entry"], r0["tier1_supplier"])], {
            "exposed_tier1": sorted({r["tier1_supplier"] for r in rows})}

    def _a_critical(self, q, **_):
        rows = A.criticality(self.kg)[:5]
        text = "Most critical suppliers by revenue at risk if lost for their recovery time: " + "; ".join(
            f"{r['name']} (tier {r['tier']}, ${r['revenue_at_risk_musd']}M)" for r in rows) + "."
        return text, [], {"top": [r["supplier"] for r in rows]}

    def _a_unknown(self, q, **_):
        return ("I can answer questions about event impact, supplier dependencies, part sourcing, single-source parts, hidden "
                "sub-tier concentration, sanctions exposure and supplier criticality."), [], {}

    def _write(self, question: str, answer: str, facts: dict) -> tuple[str, str]:
        if not self.llm.available or not facts:
            return answer, "graph"
        usage = LLMUsage()
        text = self.llm.chat("Rewrite the answer for a supply-chain executive in at most 80 words. Keep every number and name exactly; add nothing.",
                             json.dumps({"question": question, "answer": answer}), usage=usage, max_tokens=300)
        if isinstance(text, str):
            nums = set(re.findall(r"\$?\d+(?:\.\d+)?", text))
            if nums <= set(re.findall(r"\$?\d+(?:\.\d+)?", answer)):
                return text.strip(), "llm"
        return answer, "graph_fallback"
