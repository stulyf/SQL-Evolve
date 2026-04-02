---
created_at: round_1
keywords:
- extreme
- join
- subquery
- order_by
- limit
last_updated: round_1
name: prefer_join_for_extreme_values
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
summary: Use JOINs with ORDER BY and LIMIT instead of subqueries when retrieving rows
  based on maximum or minimum values.
---

## Rules

1. When the question involves finding the row with the highest or lowest value (e.g., 'maximum', 'minimum', 'top', 'bottom'), prefer a JOIN between relevant tables with ORDER BY and LIMIT 1 over subqueries using MAX/MIN or aggregation.
2. Ensure the JOIN condition correctly links the tables on foreign keys or matching columns to avoid missing or extra joins.
3. If multiple tables are referenced, join only the necessary tables directly involved in the extreme value calculation and data retrieval, avoiding intermediate tables unless required for filtering.

## Examples

❌ Bad: SELECT column_X FROM table_A WHERE key = (SELECT key FROM table_B ORDER BY value DESC LIMIT 1)
✅ Good: SELECT table_A.column_X FROM table_A INNER JOIN table_B ON table_A.key = table_B.key ORDER BY table_B.value DESC LIMIT 1

❌ Bad: SELECT column_Y FROM table_C WHERE key = (SELECT key FROM table_D WHERE value = (SELECT MAX(value) FROM table_D))
✅ Good: SELECT table_C.column_Y FROM table_C INNER JOIN table_D ON table_C.key = table_D.key ORDER BY table_D.value DESC LIMIT 1
