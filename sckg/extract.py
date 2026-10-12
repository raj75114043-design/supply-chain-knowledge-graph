"""Information extraction from supplier documents: sentences → typed relations with provenance.

The rule extractor uses relation patterns written for supplier-audit, sub-tier-disclosure, ownership and risk-alert
language. An optional LLM extractor (Groq / Ollama) proposes additional triples as JSON; they are accepted only if
they match the ontology and both arguments occur verbatim in the sentence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sckg.llm import LLMClient, LLMUsage

ABBREV = r"(?<!\bCo)(?<!\bLtd)(?<!\bCorp)(?<!\bK\.K)(?<!\bS\.A)(?<!\bC\.V)(?<!\bo\.o)(?<!\bInc)(?<!\bBhd)"
SENT_SPLIT = re.compile(ABBREV + r"(?<=[.;])\s+(?=[A-Z])")
ORG = r"(?P<{n}>[A-Z][\w&'.,-]*(?:\s+(?:[A-Z][\w&'.,-]*|&|de|sp\.|z|o\.o\.))*)"
COMP = r"(?P<comp>[A-Za-z][\w -]+?)"
CITY = r"(?P<city>[A-Z][a-z]+(?: [A-Z][a-z]+)?)"


def org(n: str) -> str:
    return ORG.format(n=n)


# (relation, pattern, head group, tail group); SUPPLIES head = supplier, tail = customer
PATTERNS = [
    ("SUPPLIES", rf"^{org('cust')} sources {COMP} from {org('sup')}\.?$", "sup", "cust"),
    ("SUPPLIES", rf"^{org('sup')} is a key supplier of {COMP} to {org('cust')}\.?$", "sup", "cust"),
    ("SUPPLIES", rf"{org('cust')} procures {COMP} from {org('sup')}, based in {CITY}\.?$", "sup", "cust"),
    ("SUPPLIES", rf"^{org('cust')} confirmed that its {COMP} come from {org('sup')}'s facility in {CITY}\.?$", "sup", "cust"),
    ("SUPPLIES", rf"{org('cust')} named {org('sup')} as the only source of {COMP}\.?$", "sup", "cust"),
    ("SUBSIDIARY_OF", rf"^{org('child')} is a subsidiary of {org('parent')}, which", "child", "parent"),
    ("LOCATED_IN", rf"^{org('org')} operates (?:its main plant|a production facility) in {CITY}", "org", "city"),
]
EVENT_WORDS = {"flood": r"flood", "earthquake": r"earthquake", "export restriction": r"export restriction", "fire": r"\bfire\b",
               "port strike": r"\bstrike\b", "typhoon": r"typhoon"}


@dataclass
class Triple:
    head: str          # surface form (mention) or event key
    relation: str
    tail: str
    doc_id: str
    sentence: str
    attrs: dict
    extractor: str = "rules"
    confidence: float = 0.9

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


LEGAL_END = re.compile(r"\b(Co|Corp|Ltd|Inc|K\.K|S\.A|C\.V|o\.o|Bhd)\.$")


def _clean(name: str) -> str:
    name = name.strip().rstrip(",")
    return name if LEGAL_END.search(name) else name.rstrip(".")


def extract_rules(doc: dict, places: dict[str, str]) -> list[Triple]:
    """`places` maps city and region names to their kind ("city" / "region")."""
    out = []
    for sent in sentences(doc["text"]):
        for rel, pat, h, t in PATTERNS:
            m = re.search(pat, sent)
            if not m:
                continue
            gd = m.groupdict()
            attrs = {"component": gd["comp"].strip()} if gd.get("comp") else {}
            tail = gd[t] if rel != "LOCATED_IN" else gd["city"]
            out.append(Triple(_clean(gd[h]), rel, _clean(tail), doc["doc_id"], sent, attrs))
            if rel == "SUPPLIES" and gd.get("city"):
                out.append(Triple(_clean(gd["sup"]), "LOCATED_IN", gd["city"], doc["doc_id"], sent, {}, confidence=0.8))
            break
    if doc.get("type") == "risk_alert":   # events are read at document level: type, place and duration may span sentences
        text = doc["text"]
        ev = next((k for k, rx in EVENT_WORDS.items() if re.search(rx, text, re.I)), None)
        weeks = re.search(r"(\d+) weeks", text)
        if ev and weeks:
            fire = re.search(rf"at {org('sup')}'s {CITY} plant", text)
            if fire:
                target, kind = _clean(fire.group("sup")), "supplier"
            else:
                locs = [p for p in places if re.search(rf"\b{re.escape(p)}\b", text)]
                regions = [p for p in locs if places[p] == "region"]
                target, kind = (regions or locs or [None])[0], "location"
            if target:
                out.append(Triple(f"{ev}@{doc['date']}", "AFFECTS", target, doc["doc_id"], text,
                                  {"event_type": ev, "weeks": int(weeks.group(1)), "date": doc["date"], "target_kind": kind}))
    return out


SUPPLY_VERBS = re.compile(r"\b(shipped|ships|originat\w*|sourced|supplied|supplies|procur\w*|purchas\w*|bought|come[s]? from|delivered)\b", re.I)
CAPS = re.compile(r"\b[A-Z][\w&.-]*(?:\s+(?:[A-Z][\w&.-]*|&|de))*")
NOT_ORG = {"Most", "The", "In", "According", "A", "An", "Its", "Their", "This", "Industry", "Authorities", "Dock", "Plants", "Severe"}


def extract_cooccurrence(doc: dict, places: dict[str, str], already: set[str]) -> list[Triple]:
    """Fallback for phrasing no pattern covers: a sentence with a supply verb and exactly two organisation-like names.
    Direction is decided later (the ERP tier-1 supplier is the customer). Low confidence; flagged for review."""
    out = []
    for sent in sentences(doc["text"]):
        if sent in already or not SUPPLY_VERBS.search(sent):
            continue
        names = [_clean(m.group(0).removesuffix("'s")) for m in CAPS.finditer(sent)]
        names = [n for n in dict.fromkeys(names) if n not in NOT_ORG and n not in places]
        if len(names) == 2:
            out.append(Triple(names[0], "CO_SUPPLY", names[1], doc["doc_id"], sent, {"component": "unspecified", "needs_review": True},
                              extractor="cooccurrence", confidence=0.6))
    return out


LLM_SYSTEM = """Extract supply-chain facts from the sentence. Return JSON {"triples": [{"head": ..., "relation": ..., "tail": ..., "component": ...}]}.
Relations: SUPPLIES (head = supplier company, tail = customer company), SUBSIDIARY_OF (head = subsidiary, tail = parent),
LOCATED_IN (head = company, tail = city). Copy company and city names exactly as written. Return {"triples": []} if none."""


def extract_llm(doc: dict, llm: LLMClient, usage: LLMUsage) -> list[Triple]:
    out = []
    for sent in sentences(doc["text"]):
        res = llm.chat(LLM_SYSTEM, sent, json_mode=True, usage=usage, max_tokens=300)
        for t in (res or {}).get("triples", []) if isinstance(res, dict) else []:
            h, r, tl = str(t.get("head", "")), str(t.get("relation", "")), str(t.get("tail", ""))
            if r in {"SUPPLIES", "SUBSIDIARY_OF", "LOCATED_IN"} and h and tl and h in sent and tl in sent:   # grounding check
                out.append(Triple(h, r, tl, doc["doc_id"], sent, {"component": t.get("component")} if t.get("component") else {},
                                  extractor="llm", confidence=0.7))
    return out


def extract(docs: list[dict], places: dict[str, str], llm: LLMClient | None = None) -> tuple[list[Triple], dict]:
    usage = LLMUsage()
    triples = [t for d in docs for t in extract_rules(d, places)]
    covered = {t.sentence for t in triples}
    triples += [t for d in docs if d.get("type") != "market_news" for t in extract_cooccurrence(d, places, covered)]
    if llm and llm.available:
        have = {(t.doc_id, t.relation, t.head, t.tail) for t in triples}
        for d in docs:
            for t in extract_llm(d, llm, usage):
                if (t.doc_id, t.relation, t.head, t.tail) not in have:
                    triples.append(t)
    return triples, {"llm_calls": usage.calls, "llm_failures": usage.failures}


def dumps(triples: list[Triple]) -> str:
    return json.dumps([t.as_dict() for t in triples], indent=1)
