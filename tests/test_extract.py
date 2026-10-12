from sckg.extract import extract_cooccurrence, extract_rules, sentences

PLACES = {"Xining": "city", "Kumamoto": "city", "Kyushu": "region"}


def test_sentence_split_keeps_legal_abbreviations():
    s = sentences("Volta Cell Systems Co., Ltd. sources cathode material from Kunlun Lithium. It is reviewing options.")
    assert len(s) == 2 and s[0].startswith("Volta Cell Systems Co., Ltd. sources")


def test_supply_pattern_and_location():
    doc = {"doc_id": "D", "type": "supplier_audit",
           "text": "According to the supplier audit, VCS procures cathode material from Kunlun Lithium, based in Xining."}
    rels = {(t.relation, t.head, t.tail) for t in extract_rules(doc, PLACES)}
    assert ("SUPPLIES", "Kunlun Lithium", "VCS") in rels and ("LOCATED_IN", "Kunlun Lithium", "Xining") in rels


def test_event_spanning_two_sentences():
    doc = {"doc_id": "D", "type": "risk_alert", "date": "2026-09-25",
           "text": "A magnitude 6.8 earthquake struck Kyushu on 2026-09-25. Plants in Kumamoto are expected to remain closed for about 6 weeks."}
    ev = [t for t in extract_rules(doc, PLACES) if t.relation == "AFFECTS"][0]
    assert ev.tail == "Kyushu" and ev.attrs["weeks"] == 6


def test_cooccurrence_fallback_needs_supply_verb():
    doc = {"doc_id": "D", "type": "analyst_note", "text": "Brightway's etching gases are shipped in from KSG, a specialty chemicals maker."}
    assert [(t.head, t.tail) for t in extract_cooccurrence(doc, PLACES, set())] == [("Brightway", "KSG")]
    doc["text"] = "Brightway and KSG signed a memorandum of understanding."
    assert extract_cooccurrence(doc, PLACES, set()) == []
