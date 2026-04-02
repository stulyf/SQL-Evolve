---
created_at: round_1
keywords:
- order by
- limit
- unnecessary
- extra clause
- distinct
last_updated: round_1
name: avoid_unnecessary_ordering_or_limiting
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
summary: Only include ORDER BY or LIMIT clauses when explicitly required by the question's
  wording or functional need.
---

## Rules

1. Do NOT add an ORDER BY clause unless the question explicitly requests sorted results (e.g., 'in alphabetical order', 'by date', 'list down').
2. Do NOT add a LIMIT clause unless the question explicitly asks for a bounded number of results (e.g., 'first', 'top', 'one', 'any') or a boolean existence check that cannot be expressed with an aggregate or conditional function.
3. For questions asking 'How many' or existence ('Is there any'), prefer using COUNT(), EXISTS, or conditional logic (IIF/CASE) that returns a single aggregated value, rather than LIMIT 1 on a SELECT.
4. When a subquery is used in an IN clause or for set membership, avoid using LIMIT 1 unless the relationship is guaranteed to be one-to-one; use IN with the full set instead.

## Examples

❌ Bad: SELECT column_a FROM table_A WHERE condition ORDER BY column_a
✅ Good: SELECT column_a FROM table_A WHERE condition

❌ Bad: SELECT id FROM table_B WHERE condition LIMIT 1
✅ Good: SELECT IIF(COUNT(*) > 0, 'YES', 'NO') FROM table_B WHERE condition
