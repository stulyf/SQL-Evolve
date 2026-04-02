---
created_at: round_1
keywords:
- table
- join
- minimal
- schema
- analysis
last_updated: round_1
name: minimal_table_join_strategy
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
summary: Select only essential tables by directly mapping question attributes to schema
  columns and avoiding unnecessary joins.
---

## Rules

1. Identify all data attributes (e.g., scores, counts, locations) mentioned in the question.
2. Map each attribute to its corresponding column in the database schema.
3. Determine the minimal set of tables that contain these columns; include a table only if it provides a required column or a necessary join key.
4. Join tables directly using foreign keys when possible, skipping intermediate tables that do not contribute to the output or filters.
5. Verify that every table in the FROM clause is essential for answering the question.

## Examples

❌ Bad: SELECT column_Z FROM table_A JOIN table_B ON table_A.key = table_B.key JOIN table_C ON table_B.key = table_C.key WHERE condition; (table_B is an unnecessary intermediate table)
✅ Good: SELECT column_Z FROM table_A JOIN table_C ON table_A.key = table_C.key WHERE condition; (direct join eliminates extra table)
