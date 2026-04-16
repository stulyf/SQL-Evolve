# -*- coding: utf-8 -*-
"""LangGraph shared state for SQLaxy."""
from typing import TypedDict


class SQLaxyState(TypedDict):
    # Input
    idx: int
    db_id: str
    query: str
    evidence: str
    extracted_schema: dict
    ground_truth: str
    difficulty: str

    # Selector output
    desc_str: str
    fk_str: str
    chosen_db_schem_dict: dict
    pruned: bool

    # Decomposer output
    final_sql: str
    qa_pairs: str

    # Refiner output
    pred: str
    fixed: bool
    try_times: int
    need_refine: bool

    # Skill injection context (progressive mode)
    skill_context: dict
