---
created_at: round_1
keywords:
- top
- highest
- rank
- order by
- limit
last_updated: round_1
name: order_by_for_ranking_queries
priority: medium
stage: decomposer
stats:
  effectiveness: 0.0
  harm_count: 0
  harm_history: []
  harm_ratio: 0.0
  help_count: 0
  help_history: []
  match_count: 0
  match_history: []
  score: 0.0
summary: Use ORDER BY with LIMIT/OFFSET instead of WHERE clauses to retrieve top or
  ranked records based on column values.
---

## Rules

1. For queries that require finding the maximum, minimum, or nth value in a set, use ORDER BY on the relevant column with appropriate direction (ASC or DESC) and LIMIT/OFFSET to select the desired row(s).
2. Avoid constructing WHERE clauses that filter using subqueries computing aggregate values like MAX or MIN for ranking purposes, as this is often unnecessary and can introduce errors.
3. Ensure that the ORDER BY clause handles potential NULL values if they affect sorting, but do not add redundant WHERE IS NOT NULL filters unless explicitly needed.

## Examples

❌ Bad: SELECT column_X FROM table_A WHERE column_Y = (SELECT MAX(column_Y) FROM table_A);
✅ Good: SELECT column_X FROM table_A ORDER BY column_Y DESC LIMIT 1;

❌ Bad: SELECT column_A FROM table_B WHERE column_Z = (SELECT DISTINCT column_Z FROM table_B ORDER BY column_Z DESC LIMIT 1 OFFSET 5);
✅ Good: SELECT column_A FROM table_B ORDER BY column_Z DESC LIMIT 5, 1;
