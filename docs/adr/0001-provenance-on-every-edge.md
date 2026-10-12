# ADR-0001: Provenance on every edge; answers are evidence paths

**Status:** Accepted · 2026-10-12

## Context
Risk decisions (expedite, dual-source, exit a supplier) need to be defensible. A number like "$460M at risk" is only
useful if a planner can see why: which document said that a gas supplier in Kumamoto feeds Brightway.

## Decision
Every edge stores a list of provenance records: source (`erp`, a document ID or the sanctions list), the sentence,
the extractor (`erp`, `rules`, `cooccurrence`, `llm`, `screening`) and a confidence. Repeated evidence appends to the list.
Q&A answers include the shortest explanation path from the event or supplier to the affected part, with the source of each hop.

## Consequences
+ Every answer can be audited; low-confidence (co-occurrence) edges are visible and reviewable.
− Edges are heavier; the Neo4j mirror stores provenance as a JSON property.
