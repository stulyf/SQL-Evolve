"""EvoSQL global configuration."""

import os

PROPOSER_MODEL = os.getenv("EVOSQL_PROPOSER_MODEL", "deepseek-reasoner")
GENERATOR_MODEL = os.getenv("EVOSQL_GENERATOR_MODEL", "deepseek-chat")
MERGE_MODEL = os.getenv("EVOSQL_MERGE_MODEL", "deepseek-chat")

PROPOSER_API_BASE = os.getenv("EVOSQL_PROPOSER_API_BASE", "https://api.deepseek.com/v1")
GENERATOR_API_BASE = os.getenv("EVOSQL_GENERATOR_API_BASE", "https://api.deepseek.com/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "")

SKILL_LIMITS = {
    "selector": 8,
    "decomposer": 12,
    "refiner": 8,
}

MERGE_THRESHOLD = 8
SKILL_MAX_TOKENS = 500

STAGES = ["selector", "decomposer", "refiner"]

ERROR_TYPES = [
    "syntax_error",
    "no_such_table",
    "no_such_column",
    "type_error",
    "wrong_table",
    "wrong_join",
    "wrong_aggregation",
    "wrong_filter",
    "wrong_subquery",
    "wrong_order",
    "wrong_select",
    "semantic_mismatch",
    "empty_result",
    "timeout",
]

CLAUSE_PRIORITY = {
    "FROM": 0,
    "JOIN": 0,
    "WHERE": 1,
    "GROUP_BY": 2,
    "HAVING": 2,
    "SELECT": 3,
    "ORDER_BY": 4,
    "LIMIT": 4,
}

SAMPLES_PER_GROUP = 5
