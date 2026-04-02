---
created_at: round_1
keywords:
- subquery
- ranking
- limit
- order
- top
last_updated: round_1
name: prefer_order_by_limit_over_subquery
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
summary: When retrieving top, bottom, or ranked values, use ORDER BY with LIMIT/OFFSET
  instead of subqueries to simplify SQL and avoid errors.
---

## Rules

1. For questions involving finding maximum, minimum, or specific ranks (e.g., highest, lowest, nth highest) in a column, avoid subqueries with aggregate functions like MAX or MIN.
2. In the main query, use ORDER BY on the relevant column (ASC for ascending, DESC for descending) to sort the data appropriately.
3. Apply LIMIT 1 for single top/bottom values, or LIMIT N OFFSET M for specific ranks, directly after the ORDER BY clause.
4. Ensure that ORDER BY and LIMIT are applied after all necessary joins and filters to maintain correct ranking across the dataset.

## Examples

❌ Bad: SELECT column_X FROM table_A WHERE column_Y = (SELECT MAX(column_Y) FROM table_A)
✅ Good: SELECT column_X FROM table_A ORDER BY column_Y DESC LIMIT 1

❌ Bad: SELECT name FROM table_B WHERE value = (SELECT DISTINCT value FROM table_B ORDER BY value DESC LIMIT 1 OFFSET 5)
✅ Good: SELECT name FROM table_B ORDER BY value DESC LIMIT 1 OFFSET 5
