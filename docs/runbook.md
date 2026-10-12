# Operations runbook

| Symptom | Check | Action |
|---|---|---|
| Revenue at risk looks too low for an event | Evidence paths; `unresolved` count in `/ready` | Missing sub-tier relation or unresolved name; add the source document, review the queue |
| Entity review queue grows | `resolver.review_queue` in the console Pipeline tab | Steward links the mention or records a new company alias |
| Unexpected sanctions match | Match score and alias | Confirm with compliance before acting; tune threshold only with evaluation |
| `neo4j-check` fails in CI | Which event differs | Cypher and Python impact logic diverged; fix and re-run |
