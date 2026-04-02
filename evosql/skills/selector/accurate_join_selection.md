---
created_at: round_1
keywords:
- join
- table
- schema
- foreign key
- minimal
last_updated: round_1
name: accurate_join_selection
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
summary: A strategy to select the correct tables and joins by mapping question attributes
  to the database schema and minimizing unnecessary joins.
---

## Rules

1. Identify all attributes required in the question, including those for output, filtering, ordering, and grouping.
2. Consult the database schema to map each attribute to its source table, noting primary and foreign keys.
3. Determine the minimal set of tables needed to access all required attributes through foreign key relationships, avoiding redundant joins.
4. Ensure that any table included contributes directly to attributes or is necessary as a bridge for joins between required tables.
5. Verify that the selected tables support all SQL clauses (e.g., WHERE, SELECT) without missing data or adding extraneous data.

## Examples

❌ Bad: SELECT column_X FROM table_A WHERE column_Y = 'value'; when column_X is in table_A but column_Y is in table_B, requiring a join.
✅ Good: SELECT a.column_X, b.column_Y FROM table_A a INNER JOIN table_B b ON a.foreign_key = b.primary_key WHERE b.column_Y = 'value';

❌ Bad: SELECT x.attr1, y.attr2, z.attr3 FROM table_X x JOIN table_Y y ON x.key = y.key JOIN table_Z z ON y.key = z.key when only attr1 and attr2 are needed from table_X and table_Y.
✅ Good: SELECT x.attr1, y.attr2 FROM table_X x INNER JOIN table_Y y ON x.key = y.key;
