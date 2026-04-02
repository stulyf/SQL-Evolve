---
created_at: round_1
keywords:
- aggregation
- group by
- unnecessary
- missing
- summary
last_updated: round_1
name: correct_aggregation_usage
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
summary: Apply aggregation functions and GROUP BY only when the question requires
  summary statistics or categorical groupings.
---

## Rules

1. Use aggregation functions (e.g., COUNT, SUM, AVG) only when the question explicitly asks for a summary measure like 'how many', 'total', or 'average'.
2. Add GROUP BY only when the question involves categorical breakdowns, such as 'for each type', 'by status', or similar grouping phrases.
3. If the question requests a list of individual items (e.g., names, schools) without implying summaries, avoid both aggregation functions and GROUP BY.
4. When selecting columns, ensure that non-aggregated columns are either part of GROUP BY or the query does not require aggregation.
5. In WHERE clauses, avoid introducing aggregation unless the condition inherently requires it, such as comparing derived values.

## Examples

❌ Bad: SELECT column_X FROM table_A WHERE condition GROUP BY column_X; (when no grouping is asked, leading to unnecessary GROUP BY)
✅ Good: SELECT column_X FROM table_A WHERE condition; (for listing individual items)

❌ Bad: SELECT column_Y FROM table_B WHERE condition; (when question asks for 'how many' or total)
✅ Good: SELECT COUNT(column_Y) FROM table_B WHERE condition; (using aggregation for summary)
