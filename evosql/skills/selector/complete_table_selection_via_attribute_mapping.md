---
created_at: round_1
keywords:
- attributes
- tables
- joins
- schema
- selection
last_updated: round_1
name: complete_table_selection_via_attribute_mapping
priority: medium
stage: selector
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
summary: Ensure all necessary tables are selected by mapping every question attribute
  to its corresponding table in the database schema.
---

## Rules

1. Extract all explicit and implicit data attributes required by the natural language question, including those inferred from context or relationships.
2. For each attribute, identify the table where it resides by consulting the database schema or common knowledge.
3. Include all identified tables in the SQL query; if multiple tables are needed, specify correct join conditions based on foreign keys or relationships.
4. Avoid including extra tables that do not contribute to the required attributes or necessary joins.

## Examples

❌ Bad: SELECT column_X FROM table_A WHERE condition_on_column_Y; (Assumes column_Y is in table_A, but it might be in another table, leading to missing tables.)
✅ Good: SELECT column_X, column_Y FROM table_A INNER JOIN table_B ON join_condition WHERE condition_on_column_Y; (Correctly joins tables to access all required attributes from their respective sources.)
