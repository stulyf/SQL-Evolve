---
created_at: round_1
keywords:
- mapping
- schema
- implicit
- conditions
- validation
last_updated: round_1
name: validate_attribute_table_mapping
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
summary: In the decomposer stage, ensure precise mapping of attributes to their correct
  tables and columns based on schema and context, avoiding unnecessary or implicit
  filters.
---

## Rules

1. For each attribute referenced in the question or evidence, explicitly identify the correct table and column from the database schema before adding it to the SQL query.
2. Avoid adding implicit conditions such as IS NOT NULL, extra equality checks (e.g., column = 1), or filters not specified in the question or evidence.
3. When joining tables, verify that WHERE clauses and selected columns are applied to the table that logically contains the data, based on the question context and schema relationships.

## Examples

❌ Bad: SELECT column_X FROM table_A INNER JOIN table_B ON table_A.id = table_B.id WHERE table_B.column_Y > 100 AND table_A.column_Z IS NOT NULL
(Assuming column_Y should be from table_A based on context, and IS NOT NULL is not specified.)
✅ Good: SELECT column_X FROM table_A INNER JOIN table_B ON table_A.id = table_B.id WHERE table_A.column_Y > 100
