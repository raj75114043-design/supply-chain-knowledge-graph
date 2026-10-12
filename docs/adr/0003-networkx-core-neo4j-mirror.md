# ADR-0003: NetworkX as the pipeline's graph; Neo4j as a verified mirror

**Status:** Accepted · 2026-10-12

## Context
The graph has under a thousand nodes and is rebuilt in milliseconds; analytics are easier to test in Python. Other
teams want Cypher and Neo4j Browser/Bloom for exploration.

## Decision
The pipeline builds and analyses a NetworkX MultiDiGraph. `sckg.cli neo4j-check` loads it into Neo4j (constraints,
batched UNWIND MERGE) and asserts that a Cypher impact query returns the same products as the Python analytics for
every event; CI runs this against a Neo4j service container.

## Consequences
+ Fast, deterministic tests; Neo4j stays consistent with the tested logic.
− Two query implementations to maintain for the impact question; at much larger scale Neo4j (or a graph DB) would become primary.
