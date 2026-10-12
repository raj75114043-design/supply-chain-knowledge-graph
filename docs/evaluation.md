# Evaluation notes

## The finding that justified the fallback extractor
The first evaluation run had extraction precision 100% and seen-phrasing recall 100%, but two relations written in
unfamiliar language ("Brightway's etching gases are shipped in from KSG…") were missed. The consequence showed up in
the analytics agreement, not the extraction score:

| Event | Gold graph | Pipeline (before) | Pipeline (after fallback) |
|---|---|---|---|
| Kyushu earthquake | $460M at risk | **$0** | $460M |

Hidden-concentration agreement also failed (Kyushu Specialty Gases feeds two tier-1 suppliers). The co-occurrence
fallback (a supply verb plus exactly two organisation names, oriented so the ERP supplier is the customer, confidence
0.6, flagged `needs_review`) recovered both.

## Caveats
* Two unseen sentences are a tiny sample; on real documents expect false positives from the fallback — hence the review flag.
* Templates make pattern extraction easy; the more meaningful tests are unseen phrasing, look-alike entity resolution and analytics agreement.
