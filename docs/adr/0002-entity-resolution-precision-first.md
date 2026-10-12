# ADR-0002: Entity resolution favours precision; ambiguity goes to people

**Status:** Accepted · 2026-10-12

## Context
Merging two different companies (a supplier and a look-alike) silently corrupts every analytic downstream — sanctions
exposure most of all. Missing a merge is cheaper: the alias stays a separate node until someone links it.

## Decision
Deterministic, explainable scoring (acronym, ordered prefix, distinctive-token subset, fuzzy token-set) with a high
threshold. When two candidates tie, an ERP supplier wins only if the mention is an argument of a supply relation;
otherwise the mention goes to a review queue. The evaluation includes look-alike companies and gates on zero false merges.

## Consequences
+ No false merges on the evaluation set; every link has a reason.
− Some true aliases may need steward review; the queue is exposed in the console and API.
