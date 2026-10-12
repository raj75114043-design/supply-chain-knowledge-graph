"""Synthetic supply chain of "Helix Motors", a fictional EV manufacturer.

Structured sources (what an ERP knows): products, BOM, parts, tier-1 suppliers with sites, sourcing shares,
inventory cover and supplier time-to-recover.
Unstructured sources (what the ERP does not know): supplier news, audit reports, sub-tier disclosures, ownership
notices and risk alerts that name companies inconsistently ("Volta Cell Systems Co., Ltd." / "Volta Cells" / "VCS").
A sanctions list with aliases. Gold annotations for entity resolution, relations and event impact.

Everything is fictional.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

REGIONS = {  # city: (region, country)
    "Shenzhen": ("Guangdong", "CN"), "Dongguan": ("Guangdong", "CN"), "Suzhou": ("Jiangsu", "CN"), "Ganzhou": ("Jiangxi", "CN"),
    "Xining": ("Qinghai", "CN"), "Hsinchu": ("Hsinchu", "TW"), "Kumamoto": ("Kyushu", "JP"), "Hwaseong": ("Gyeonggi", "KR"),
    "Regensburg": ("Bavaria", "DE"), "Bayan Lepas": ("Penang", "MY"), "Sanand": ("Gujarat", "IN"), "Tijuana": ("Baja California", "MX"),
    "Wroclaw": ("Lower Silesia", "PL"), "Gdansk": ("Pomerania", "PL"),
}

# Tier-1 suppliers known to the ERP: id, legal name, aliases used in documents, site city
TIER1 = [
    ("S01", "Volta Cell Systems Co., Ltd.", ["Volta Cell Systems", "Volta Cells", "VCS"], "Suzhou"),
    ("S02", "Arclight Power Electronics GmbH", ["Arclight Power", "Arclight"], "Regensburg"),
    ("S03", "Kiyomi Semiconductor K.K.", ["Kiyomi Semi", "Kiyomi Semiconductor"], "Kumamoto"),
    ("S04", "Hanbit Display Co.", ["Hanbit Display", "Hanbit"], "Hwaseong"),
    ("S05", "Penang Precision Sensors Sdn Bhd", ["Penang Precision", "PPS"], "Bayan Lepas"),
    ("S06", "Tijuana Harness Works S.A. de C.V.", ["Tijuana Harness", "THW"], "Tijuana"),
    ("S07", "Sanand Steel & Stampings Pvt Ltd", ["Sanand Steel", "Sanand Steel & Stampings"], "Sanand"),
    ("S08", "Rotorix Motors Ltd", ["Rotorix", "Rotorix Motors"], "Wroclaw"),
    ("S09", "Dongguan Lumen Optics Co., Ltd.", ["Lumen Optics", "DG Lumen Optics"], "Dongguan"),
    ("S10", "Silesia Seating Systems sp. z o.o.", ["Silesia Seating", "Silesia Seating Systems"], "Wroclaw"),
    ("S11", "Shenzhen Brightway Electronics Co., Ltd.", ["Brightway Electronics", "Brightway"], "Shenzhen"),
    ("S12", "Nordlicht Glas AG", ["Nordlicht Glas", "Nordlicht"], "Regensburg"),
    ("S13", "Hwaseong Energy Solutions Co.", ["Hwaseong Energy", "HES"], "Hwaseong"),
]
# Sub-tier companies that appear only in documents: id, canonical name, aliases, city
TIER2 = [
    ("X01", "Kunlun Lithium Materials Ltd", ["Kunlun Lithium", "Kunlun Lithium Materials"], "Xining"),
    ("X02", "Ganzhou Rare Earth Magnetics Co.", ["Ganzhou Magnetics", "GREM"], "Ganzhou"),
    ("X03", "Formosa Wafer Foundry Corp.", ["Formosa Wafer", "FWF"], "Hsinchu"),
    ("X04", "Baltic Copper Rolling S.A.", ["Baltic Copper", "Baltic Copper Rolling"], "Gdansk"),
    ("X05", "Kyushu Specialty Gases K.K.", ["Kyushu Specialty Gases", "KSG"], "Kumamoto"),
]
# Different companies whose names look like suppliers' names (entity-resolution traps)
DISTRACTORS = [("Y01", "Volta Mobility Ventures", []), ("Y02", "Penang Precision Tooling Sdn Bhd", ["Penang Precision Tooling"]),
               ("Y03", "Kiyomi Foods Co.", ["Kiyomi Foods"]), ("Y04", "Arclight Media Group", ["Arclight Media"])]
PARENTS = [("X06", "Altai Mineral Holdings Limited", ["Altai Mineral Holdings", "Altai Minerals"])]
SANCTIONS = [{"list_id": "SL-0417", "name": "ALTAI MINERAL HOLDINGS LIMITED", "aliases": ["ALTAI MINERALS", "AMH LTD"], "program": "Critical minerals export controls"},
             {"list_id": "SL-0388", "name": "NORTHERN STAR SHIPPING LLC", "aliases": ["NSS LLC"], "program": "Maritime"}]

PRODUCTS = [("HX-AERO", "Helix Aero", 42.0), ("HX-TERRA", "Helix Terra", 55.0), ("HX-CARGO", "Helix Cargo", 18.0)]   # weekly revenue, $M
ASSEMBLIES = {
    "A-BAT": ("Battery pack", ["P-1001", "P-1002", "P-1003"]),
    "A-DRV": ("Drive unit", ["P-2001", "P-2002"]),
    "A-INF": ("Infotainment unit", ["P-3001", "P-3002"]),
    "A-ADS": ("ADAS module", ["P-4001", "P-4002"]),
    "A-ELE": ("Electrical system", ["P-5001", "P-9001"]),
    "A-BIW": ("Body in white", ["P-6001", "P-8001"]),
    "A-SEA": ("Seating", ["P-7001"]),
}
PRODUCT_BOM = {"HX-AERO": list(ASSEMBLIES), "HX-TERRA": list(ASSEMBLIES),
               "HX-CARGO": ["A-BAT", "A-DRV", "A-ELE", "A-BIW", "A-SEA", "A-ADS"]}
PARTS = {  # part: (name, inventory weeks, [(supplier, share, time-to-recover weeks)])
    "P-1001": ("Lithium-ion cell", 3, [("S01", 0.7, 10), ("S13", 0.3, 8)]),
    "P-1002": ("BMS controller chip", 6, [("S03", 1.0, 16)]),
    "P-1003": ("BMS board", 2, [("S11", 1.0, 6)]),
    "P-2001": ("SiC inverter module", 4, [("S02", 1.0, 12)]),
    "P-2002": ("Drive motor", 3, [("S08", 1.0, 10)]),
    "P-3001": ("Infotainment display", 5, [("S04", 1.0, 8)]),
    "P-3002": ("Main MCU", 8, [("S03", 1.0, 16)]),
    "P-4001": ("Front radar", 4, [("S05", 1.0, 9)]),
    "P-4002": ("Camera module", 3, [("S09", 0.6, 6), ("S05", 0.4, 6)]),
    "P-5001": ("Main wiring harness", 1, [("S06", 1.0, 8)]),
    "P-6001": ("Body side panel set", 2, [("S07", 1.0, 6)]),
    "P-7001": ("Seat frame with motors", 2, [("S10", 1.0, 5)]),
    "P-8001": ("Windshield", 3, [("S12", 1.0, 6)]),
    "P-9001": ("Charging port module", 2, [("S11", 1.0, 6)]),
}
# Ground-truth sub-tier relations: (tier-2, tier-1, component)
SUBTIER = [("X01", "S01", "cathode material"), ("X01", "S13", "cathode material"), ("X02", "S08", "NdFeB magnets"),
           ("X02", "S10", "seat-motor magnets"), ("X03", "S03", "silicon wafers"), ("X03", "S11", "power-management ICs"),
           ("X03", "S05", "radar chipsets"), ("X04", "S06", "copper wire rod"), ("X04", "S08", "copper windings"),
           ("X05", "S03", "process gases")]
# Relations stated only in phrasing the rule extractor was not written for (tests generalisation; an LLM extractor can recover them)
PARAPHRASED = [("X05", "S11", "etching gases", "{t1}'s etching gases are shipped in from {t2}, a specialty chemicals maker."),
               ("X01", "S01", "lithium hydroxide", "Most of the lithium hydroxide used by {t1} originates at {t2}.")]
OWNERSHIP = [("X02", "X06")]   # Ganzhou Magnetics is a subsidiary of Altai Mineral Holdings (sanctioned)
EVENTS = [  # id, type, location (city or region or supplier id), weeks, date
    ("EV-01", "flood", "Guangdong", 3, "2026-09-18"),
    ("EV-02", "earthquake", "Kyushu", 6, "2026-09-25"),
    ("EV-03", "export restriction", "Jiangxi", 12, "2026-10-02"),
    ("EV-04", "fire", "S06", 4, "2026-10-05"),
    ("EV-05", "port strike", "Gdansk", 2, "2026-10-07"),
    ("EV-06", "typhoon", "Hsinchu", 2, "2026-10-09"),
]

SUPPLY_T = [
    "{t1} sources {comp} from {t2}.",
    "{t2} is a key supplier of {comp} to {t1}.",
    "According to the supplier audit, {t1} procures {comp} from {t2}, based in {city}.",
    "{t1} confirmed that its {comp} come from {t2}'s facility in {city}.",
    "In its sub-tier disclosure, {t1} named {t2} as the only source of {comp}.",
]
EVENT_T = {
    "flood": "Severe flooding in {loc} has disrupted factories around {cities}; operations are expected to be halted for {n} weeks.",
    "earthquake": "A magnitude 6.8 earthquake struck {loc} on {date}. Plants in {cities} are expected to remain closed for about {n} weeks.",
    "export restriction": "Authorities announced export restrictions on rare earth magnets from {loc}, effective {date} and expected to last {n} weeks.",
    "fire": "A fire broke out at {sup}'s {cities} plant on {date}; the company estimates {n} weeks to restore full production.",
    "port strike": "Dock workers at the port of {loc} began a strike on {date}; analysts expect {n} weeks of disruption to outbound cargo.",
    "typhoon": "A typhoon made landfall near {loc} on {date}; fabs in {cities} expect {n} weeks before output normalises.",
}
NOISE = [
    "{a} reported quarterly revenue growth of {p}% and reaffirmed its full-year guidance.",
    "{a} appointed a new chief operating officer with effect from next month.",
    "{a} and {b} signed a memorandum of understanding on sustainability reporting.",
    "{a} opened a new customer experience centre and expanded its engineering team.",
    "Industry analysts expect demand for electric vehicles to grow steadily next year.",
]


def _alias(rng, canonical, aliases):
    return rng.choice([canonical] + aliases * 2)


def generate(seed: int = 7) -> dict:
    rng = random.Random(seed)
    names = {i: (n, a, c) for i, n, a, c in TIER1 + TIER2} | {i: (n, a, None) for i, n, a in PARENTS + DISTRACTORS}
    docs, gold_mentions, gold_rel = [], [], []

    def add_doc(kind, title, text, date, mentions, relations):
        did = f"DOC-{len(docs) + 1:03d}"
        docs.append({"doc_id": did, "type": kind, "date": date, "title": title, "text": text})
        gold_mentions.extend({"doc_id": did, "mention": m, "entity_id": e} for m, e in mentions)
        gold_rel.extend({**r, "doc_id": did} for r in relations)

    for t2, t1, comp in SUBTIER:
        n1, a1, _ = names[t1]
        n2, a2, city = names[t2]
        m1, m2 = _alias(rng, n1, a1), _alias(rng, n2, a2)
        text = rng.choice(SUPPLY_T).format(t1=m1, t2=m2, comp=comp, city=city)
        extra = rng.choice(["", f" {m2} operates its main plant in {city}.", f" {m1} said it is reviewing dual sourcing options."])
        rels = [{"head": t2, "relation": "SUPPLIES", "tail": t1, "component": comp}]
        if city in text + extra:
            rels.append({"head": t2, "relation": "LOCATED_IN", "tail": city})
        add_doc(rng.choice(["supplier_audit", "subtier_disclosure", "supplier_news"]), f"Sub-tier sourcing: {m1}",
                text + extra, f"2026-0{rng.randint(6, 9)}-{rng.randint(10, 28)}", [(m1, t1), (m2, t2)], rels)
    for t2, t1, comp, sentence in PARAPHRASED:
        n1, a1, _ = names[t1]
        n2, a2, _ = names[t2]
        m1, m2 = _alias(rng, n1, a1), _alias(rng, n2, a2)
        add_doc("analyst_note", f"Analyst note: {m1}", sentence.format(t1=m1, t2=m2), "2026-09-30", [(m1, t1), (m2, t2)],
                [{"head": t2, "relation": "SUPPLIES", "tail": t1, "component": comp, "phrasing": "unseen"}])
    for t2, _, _, city in TIER2:   # every sub-tier company gets an explicit location statement
        n2, a2, _ = names[t2]
        m2 = _alias(rng, n2, a2)
        add_doc("supplier_profile", f"Company profile: {m2}", f"{m2} operates a production facility in {city}, {REGIONS[city][0]}.",
                "2026-05-02", [(m2, t2)], [{"head": t2, "relation": "LOCATED_IN", "tail": city}])
    for child, parent in OWNERSHIP:
        nc, ac, _ = names[child]
        npar, apar, _ = names[parent]
        mc, mp = _alias(rng, nc, ac), _alias(rng, npar, apar)
        add_doc("ownership_notice", f"Ownership: {mc}", f"{mc} is a subsidiary of {mp}, which acquired a controlling stake in 2024.",
                "2026-04-11", [(mc, child), (mp, parent)], [{"head": child, "relation": "SUBSIDIARY_OF", "tail": parent}])
    for eid, etype, loc, weeks, date in EVENTS:
        if loc in names:
            sup, a, city = names[loc]
            m = _alias(rng, sup, a)
            text = EVENT_T[etype].format(sup=m, cities=city, n=weeks, date=date, loc=REGIONS[city][0])
            mentions, target = [(m, loc)], {"supplier": loc}
        else:
            cities = [c for c, (r, _) in REGIONS.items() if r == loc or c == loc]
            text = EVENT_T[etype].format(loc=loc, cities=" and ".join(cities), n=weeks, date=date, sup="")
            mentions, target = [], {"location": loc}
        add_doc("risk_alert", f"Risk alert: {etype} – {loc if loc not in names else names[loc][0]}", text, date, mentions,
                [{"head": eid, "relation": "AFFECTS", "tail": loc, "event_type": etype, "weeks": weeks, "date": date, **target}])
    for _ in range(14):   # noise: entity mentions with no supply-chain relation
        (ia, (na, aa, _)), (ib, (nb, ab, _)) = rng.sample([(k, v) for k, v in names.items() if k.startswith(("S", "X"))], 2)
        ma, mb = _alias(rng, na, aa), _alias(rng, nb, ab)
        t = rng.choice(NOISE)
        mentions = [(ma, ia)] + ([(mb, ib)] if "{b}" in t else [])
        add_doc("market_news", f"News: {ma}", t.format(a=ma, b=mb, p=rng.randint(3, 18)), f"2026-0{rng.randint(5, 9)}-0{rng.randint(1, 9)}", mentions, [])
    for did, (nm, al, _) in [(k, names[k]) for k, *_ in DISTRACTORS]:
        m = _alias(rng, nm, al)
        add_doc("market_news", f"News: {m}", rng.choice(NOISE[:2]).format(a=m, p=rng.randint(3, 18)), "2026-07-15", [(m, did)], [])
    rng.shuffle(docs)
    for i, d in enumerate(sorted(docs, key=lambda d: (d["date"], d["title"])), start=1):
        old = d["doc_id"]
        d["doc_id"] = f"D-{i:03d}"
        for g in gold_mentions + gold_rel:
            if g["doc_id"] == old and not g.get("_done"):
                g["doc_id"], g["_done"] = d["doc_id"], True
    for g in gold_mentions + gold_rel:
        g.pop("_done", None)

    erp = {
        "products": [{"product_id": p, "name": n, "weekly_revenue_musd": r} for p, n, r in PRODUCTS],
        "assemblies": [{"assembly_id": a, "name": n} for a, (n, _) in ASSEMBLIES.items()],
        "bom": [{"parent": p, "child": a} for p, al in PRODUCT_BOM.items() for a in al] +
               [{"parent": a, "child": part} for a, (_, parts) in ASSEMBLIES.items() for part in parts],
        "parts": [{"part_id": p, "name": n, "inventory_weeks": inv} for p, (n, inv, _) in PARTS.items()],
        "sourcing": [{"part_id": p, "supplier_id": s, "share": sh, "ttr_weeks": ttr} for p, (_, _, srcs) in PARTS.items() for s, sh, ttr in srcs],
        "suppliers": [{"supplier_id": i, "legal_name": n, "site_city": c, "region": REGIONS[c][0], "country": REGIONS[c][1]} for i, n, _, c in TIER1],
    }
    gold = {"entities": {i: {"name": n, "aliases": a, "tier": 1 if i.startswith("S") else 2 if i in {x[0] for x in TIER2} else 3 if i.startswith("X") else None}
                         for i, (n, a, _) in names.items()},
            "mentions": gold_mentions, "relations": gold_rel}
    return {"erp": erp, "documents": sorted(docs, key=lambda d: d["doc_id"]), "sanctions": SANCTIONS, "gold": gold,
            "regions": [{"city": c, "region": r, "country": k} for c, (r, k) in REGIONS.items()]}


def write(seed: int = 7) -> None:
    data = generate(seed)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "erp.json").write_text(json.dumps(data["erp"], indent=1))
    (RAW / "documents.jsonl").write_text("\n".join(json.dumps(d) for d in data["documents"]) + "\n")
    (RAW / "sanctions.json").write_text(json.dumps(data["sanctions"], indent=1))
    (RAW / "regions.json").write_text(json.dumps(data["regions"], indent=1))
    (ROOT / "data" / "gold.json").write_text(json.dumps(data["gold"], indent=1))
    print(f"wrote {len(data['documents'])} documents, {len(data['gold']['relations'])} gold relations")


if __name__ == "__main__":
    write()
