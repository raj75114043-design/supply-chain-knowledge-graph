"""Entity resolution for company names.

Documents name the same company in many ways ("Volta Cell Systems Co., Ltd.", "Volta Cells", "VCS"). Resolution:
  1. normalise: lower-case, strip punctuation and legal-form tokens (Co., Ltd., GmbH, K.K., Sdn Bhd, S.A. de C.V., …), singularise
  2. score a mention against each known entity, keeping the best of
       - acronym match ("VCS" ↔ volta cell systems)                         0.97
       - ordered token-prefix match ("Kiyomi Semi" ↔ kiyomi semiconductor)   0.95
       - token subset ignoring place names ("Brightway" ↔ shenzhen brightway electronics)  0.92
       - fuzzy token-set ratio (rapidfuzz)
  3. link above THRESHOLD, otherwise create a new entity (sub-tier companies are not in the ERP)
Long mentions are resolved before short ones so acronyms can attach to an entity whose full name has been seen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

LEGAL = {"co", "ltd", "limited", "gmbh", "kk", "k", "sdn", "bhd", "sa", "de", "cv", "pvt", "inc", "corp", "corporation", "ag", "sp", "z",
         "oo", "llc", "plc", "the"}
PLACES = {"shenzhen", "dongguan", "suzhou", "ganzhou", "xining", "hsinchu", "kumamoto", "hwaseong", "regensburg", "penang", "sanand",
          "tijuana", "wroclaw", "gdansk", "kyushu", "silesia", "baltic", "dg"}
THRESHOLD = 0.86


def _sing(t: str) -> str:
    return t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t


def norm_tokens(name: str) -> list[str]:
    name = re.sub(r"'s\b", "", name.lower()).replace("&", " and ")
    toks = re.findall(r"[a-z0-9]+", name.replace(".", ""))
    return [_sing(t) for t in toks if t not in LEGAL and t != "and"]


def acronym(tokens: list[str]) -> str:
    return "".join(t[0] for t in tokens if t)


def score(mention: str, entity_names: list[str]) -> float:
    m = norm_tokens(mention)
    if not m:
        return 0.0
    best = 0.0
    for name in entity_names:
        e = norm_tokens(name)
        if not e:
            continue
        if len(m) == 1 and len(m[0]) >= 2 and m[0] == acronym(e) and len(e) >= 2:
            best = max(best, 0.97)
        if len(m) <= len(e) and all(e[i].startswith(m[i]) for i in range(len(m))):
            best = max(best, 0.95)
        distinctive = [t for t in m if t not in PLACES]
        if distinctive and all(any(et.startswith(t) for et in e) for t in distinctive) and len(distinctive) >= max(1, len(m) - 1):
            best = max(best, 0.92)
        best = max(best, fuzz.token_set_ratio(" ".join(m), " ".join(e)) / 100 * (0.98 if len(m) > 1 else 0.85))
    return best


@dataclass
class Entity:
    entity_id: str
    name: str
    names: set[str] = field(default_factory=set)
    source: str = "erp"
    tier: int | None = None


class Resolver:
    def __init__(self, known: list[Entity], threshold: float = THRESHOLD):
        self.entities: dict[str, Entity] = {e.entity_id: e for e in known}
        self.threshold = threshold
        self._new = 0
        self.review_queue: list[dict] = []

    def candidates(self, mention: str, k: int = 3) -> list[tuple[str, float]]:
        scored = [(e.entity_id, round(score(mention, [e.name, *e.names]), 3)) for e in self.entities.values()]
        return sorted(scored, key=lambda x: -x[1])[:k]

    def resolve(self, mention: str, create: bool = True, supply_context: bool = False) -> tuple[str | None, float]:
        """`supply_context`: the mention is an argument of a supply-chain relation, so an ERP supplier wins a tie."""
        cands = self.candidates(mention, 3)
        if cands and cands[0][1] >= self.threshold:
            tied = [c for c in cands if c[1] >= self.threshold and cands[0][1] - c[1] < 0.02]
            if len(tied) > 1:
                erp = [c for c in tied if self.entities[c[0]].source == "erp"]
                if supply_context and len(erp) == 1:
                    cands = erp
                else:   # genuinely ambiguous: do not guess, send to a data steward
                    self.review_queue.append({"mention": mention, "candidates": [(c[0], self.entities[c[0]].name, c[1]) for c in tied]})
                    return None, cands[0][1]
            self.entities[cands[0][0]].names.add(mention)
            return cands[0][0], cands[0][1]
        if not create:
            return None, cands[0][1] if cands else 0.0
        self._new += 1
        eid = f"N{self._new:03d}"
        self.entities[eid] = Entity(eid, mention, {mention}, source="documents")
        return eid, 1.0

    def resolve_all(self, mentions: list[str], supply_context: set[str] | None = None) -> dict[str, tuple[str | None, float]]:
        """Resolve long mentions first so that short forms (acronyms) can attach to them."""
        out, ctx = {}, supply_context or set()
        for m in sorted(set(mentions), key=lambda s: (-len(norm_tokens(s)), -len(s))):
            out[m] = self.resolve(m, supply_context=m in ctx)
        for eid, e in self.entities.items():   # canonical name for new entities = longest observed form
            if e.source == "documents":
                e.name = max(e.names, key=len)
                out.update({n: (eid, out.get(n, (eid, 1.0))[1]) for n in e.names})
        return out
