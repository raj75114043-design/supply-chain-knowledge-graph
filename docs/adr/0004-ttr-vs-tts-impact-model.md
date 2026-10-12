# ADR-0004: Time-to-recover vs. time-to-survive impact model

**Status:** Accepted · 2026-10-12

## Context
"Which products are affected" over-alarms: many disruptions are absorbed by inventory. Planners need lost production.

## Decision
For each part: share lost (sum of sourcing shares of disrupted suppliers) × weeks lost (disruption − inventory weeks,
floored at zero). A product's loss is the maximum over its parts; revenue at risk is weekly revenue × that loss.
Supplier stress tests use the supplier's time to recover (tier-1 from sourcing data; sub-tier from the longest TTR of its customers).

## Consequences
+ Distinguishes exposed-but-buffered from losing production; explains the binding part.
− Ignores capacity flex at the alternate source and partial builds; documented as a limitation.
