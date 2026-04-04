"""Error analysis: classify errors, locate stage, split error points, assign root cause."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sqlparse
from sqlparse.sql import IdentifierList, Identifier, Where, Parenthesis
from sqlparse.tokens import Keyword, DML


@dataclass
class ErrorPoint:
    clause: str  # SELECT / FROM / JOIN / WHERE / GROUP_BY / ORDER_BY / LIMIT / HAVING
    error_type: str
    is_primary: bool = True
    detail: str = ""


@dataclass
class AnalyzedError:
    question_id: int
    db_id: str
    question: str
    evidence: str
    difficulty: str
    pred_sql: str
    gold_sql: str
    error_stage: str  # selector / decomposer / refiner
    error_points: list[ErrorPoint] = field(default_factory=list)
    extracted_schema: dict = field(default_factory=dict)
    chosen_schema: dict = field(default_factory=dict)
    pruned: bool = False
    try_times: int = 0
    fixed: bool = False


def _normalize_sql(sql: str) -> str:
    sql = sql.strip().rstrip(";")
    sql = re.sub(r"\s+", " ", sql)
    return sql.upper()


def _extract_tables(sql_upper: str) -> set[str]:
    """Extract table names from SQL (rough but effective)."""
    tables = set()
    for m in re.finditer(r"\bFROM\s+(\w+)", sql_upper):
        tables.add(m.group(1))
    for m in re.finditer(r"\bJOIN\s+(\w+)", sql_upper):
        tables.add(m.group(1))
    return tables


def _extract_columns(sql_upper: str) -> set[str]:
    """Extract column references (simplified)."""
    cols = set()
    for m in re.finditer(r"(?:T\d+\.)?`?(\w[\w\s()%-]*?)`?(?:\s*[=<>!]|\s+(?:AS|IS|IN|LIKE|BETWEEN|NOT|DESC|ASC)|\s*,|\s*\)|\s*$)", sql_upper):
        col = m.group(1).strip()
        if col and col not in {"SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "NULL",
                                "ORDER", "BY", "GROUP", "LIMIT", "HAVING", "JOIN",
                                "INNER", "LEFT", "RIGHT", "ON", "AS", "IN", "BETWEEN",
                                "LIKE", "DISTINCT", "CASE", "WHEN", "THEN", "ELSE", "END",
                                "ASC", "DESC", "COUNT", "SUM", "AVG", "MAX", "MIN", "CAST",
                                "REAL", "INTEGER", "TEXT", "FLOAT"}:
            cols.add(col)
    return cols


def _has_clause(sql_upper: str, keyword: str) -> bool:
    pattern = keyword.replace("_", r"\s+")
    return bool(re.search(rf"\b{pattern}\b", sql_upper))


def _has_aggregation(sql_upper: str) -> bool:
    return bool(re.search(r"\b(COUNT|SUM|AVG|MAX|MIN)\s*\(", sql_upper))


def _has_subquery(sql_upper: str) -> bool:
    count = sql_upper.count("SELECT")
    return count > 1


def _extract_join_count(sql_upper: str) -> int:
    return len(re.findall(r"\bJOIN\b", sql_upper))


def _extract_select_columns(sql_upper: str) -> list[str]:
    """Extract column expressions from the SELECT clause."""
    m = re.search(r"\bSELECT\s+(.*?)\s+FROM\b", sql_upper, re.DOTALL)
    if not m:
        return []
    cols_str = m.group(1)
    cols = [c.strip() for c in cols_str.split(",")]
    return cols


def _extract_where_conditions(sql_upper: str) -> str:
    """Extract the WHERE clause content."""
    m = re.search(r"\bWHERE\s+(.*?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|\bHAVING\b|$)", sql_upper, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_aggregation_funcs(sql_upper: str) -> list[str]:
    """Extract aggregation function calls."""
    return re.findall(r"\b(COUNT|SUM|AVG|MAX|MIN)\s*\([^)]*\)", sql_upper)


def _classify_clause_errors(pred_upper: str, gold_upper: str) -> list[ErrorPoint]:
    """Compare predicted vs gold SQL clause by clause and produce error points."""
    points: list[ErrorPoint] = []

    pred_tables = _extract_tables(pred_upper)
    gold_tables = _extract_tables(gold_upper)

    if pred_tables != gold_tables:
        missing = gold_tables - pred_tables
        extra = pred_tables - gold_tables
        detail_parts = []
        if missing:
            detail_parts.append(f"missing tables: {missing}")
        if extra:
            detail_parts.append(f"extra tables: {extra}")
        points.append(ErrorPoint(
            clause="FROM",
            error_type="wrong_table",
            is_primary=True,
            detail="; ".join(detail_parts),
        ))

    pred_joins = _extract_join_count(pred_upper)
    gold_joins = _extract_join_count(gold_upper)
    if pred_joins != gold_joins:
        points.append(ErrorPoint(
            clause="JOIN",
            error_type="wrong_join",
            is_primary=True,
            detail=f"pred has {pred_joins} JOINs, gold has {gold_joins}",
        ))

    pred_has_gb = _has_clause(pred_upper, "GROUP BY")
    gold_has_gb = _has_clause(gold_upper, "GROUP BY")
    pred_has_agg = _has_aggregation(pred_upper)
    gold_has_agg = _has_aggregation(gold_upper)

    if pred_has_gb != gold_has_gb or pred_has_agg != gold_has_agg:
        detail = ""
        if gold_has_gb and not pred_has_gb:
            detail = "missing GROUP BY"
        elif pred_has_gb and not gold_has_gb:
            detail = "unnecessary GROUP BY"
        if gold_has_agg and not pred_has_agg:
            detail += "; missing aggregation function"
        elif pred_has_agg and not gold_has_agg:
            detail += "; unnecessary aggregation function"
        points.append(ErrorPoint(
            clause="GROUP_BY",
            error_type="wrong_aggregation",
            is_primary=False,
            detail=detail.strip("; "),
        ))

    pred_has_where = _has_clause(pred_upper, "WHERE")
    gold_has_where = _has_clause(gold_upper, "WHERE")
    if pred_has_where != gold_has_where:
        detail = "missing WHERE" if gold_has_where else "unnecessary WHERE"
        points.append(ErrorPoint(
            clause="WHERE",
            error_type="wrong_filter",
            is_primary=False,
            detail=detail,
        ))

    pred_has_sub = _has_subquery(pred_upper)
    gold_has_sub = _has_subquery(gold_upper)
    if pred_has_sub != gold_has_sub:
        detail = "pred uses subquery, gold does not" if pred_has_sub else "gold uses subquery, pred does not"
        points.append(ErrorPoint(
            clause="WHERE",
            error_type="wrong_subquery",
            is_primary=False,
            detail=detail,
        ))

    pred_has_order = _has_clause(pred_upper, "ORDER BY")
    gold_has_order = _has_clause(gold_upper, "ORDER BY")
    pred_has_limit = _has_clause(pred_upper, "LIMIT")
    gold_has_limit = _has_clause(gold_upper, "LIMIT")

    if pred_has_order != gold_has_order or pred_has_limit != gold_has_limit:
        detail_parts = []
        if gold_has_order and not pred_has_order:
            detail_parts.append("missing ORDER BY")
        if gold_has_limit and not pred_has_limit:
            detail_parts.append("missing LIMIT")
        if pred_has_order and not gold_has_order:
            detail_parts.append("unnecessary ORDER BY")
        if pred_has_limit and not gold_has_limit:
            detail_parts.append("unnecessary LIMIT")
        points.append(ErrorPoint(
            clause="ORDER_BY",
            error_type="wrong_order",
            is_primary=False,
            detail="; ".join(detail_parts),
        ))
    elif pred_has_order and gold_has_order:
        pred_desc = "DESC" in pred_upper.split("ORDER BY")[-1]
        gold_desc = "DESC" in gold_upper.split("ORDER BY")[-1]
        if pred_desc != gold_desc:
            points.append(ErrorPoint(
                clause="ORDER_BY",
                error_type="wrong_order",
                is_primary=False,
                detail="ORDER BY direction mismatch (ASC vs DESC)",
            ))

    if not points:
        points.extend(_deep_semantic_analysis(pred_upper, gold_upper))

    if not points:
        points.append(ErrorPoint(
            clause="SELECT",
            error_type="semantic_mismatch",
            is_primary=False,
            detail="SQL structures look similar but produce different results",
        ))

    _assign_primary(points)
    return points


def _deep_semantic_analysis(pred_upper: str, gold_upper: str) -> list[ErrorPoint]:
    """Fine-grained analysis for cases where structural checks find nothing."""
    points: list[ErrorPoint] = []

    pred_cols = _extract_select_columns(pred_upper)
    gold_cols = _extract_select_columns(gold_upper)
    if pred_cols != gold_cols:
        points.append(ErrorPoint(
            clause="SELECT",
            error_type="wrong_select",
            is_primary=False,
            detail=f"SELECT columns differ: pred={pred_cols[:3]}, gold={gold_cols[:3]}",
        ))

    pred_where = _extract_where_conditions(pred_upper)
    gold_where = _extract_where_conditions(gold_upper)
    if pred_where != gold_where and (pred_where or gold_where):
        detail_parts = []
        if not pred_where:
            detail_parts.append("pred missing WHERE conditions")
        elif not gold_where:
            detail_parts.append("pred has extra WHERE conditions")
        else:
            detail_parts.append(f"WHERE conditions differ")
        points.append(ErrorPoint(
            clause="WHERE",
            error_type="wrong_filter",
            is_primary=False,
            detail="; ".join(detail_parts),
        ))

    pred_aggs = _extract_aggregation_funcs(pred_upper)
    gold_aggs = _extract_aggregation_funcs(gold_upper)
    if sorted(pred_aggs) != sorted(gold_aggs):
        points.append(ErrorPoint(
            clause="SELECT",
            error_type="wrong_aggregation",
            is_primary=False,
            detail=f"aggregation functions differ: pred={pred_aggs}, gold={gold_aggs}",
        ))

    pred_has_distinct = "DISTINCT" in pred_upper
    gold_has_distinct = "DISTINCT" in gold_upper
    if pred_has_distinct != gold_has_distinct:
        detail = "missing DISTINCT" if gold_has_distinct else "unnecessary DISTINCT"
        points.append(ErrorPoint(
            clause="SELECT",
            error_type="wrong_select",
            is_primary=False,
            detail=detail,
        ))

    return points


def _assign_primary(points: list[ErrorPoint]) -> None:
    """Mark root-cause error points as primary based on clause priority."""
    from .config import CLAUSE_PRIORITY

    if not points:
        return

    min_priority = min(CLAUSE_PRIORITY.get(p.clause, 99) for p in points)
    for p in points:
        p.is_primary = CLAUSE_PRIORITY.get(p.clause, 99) == min_priority


def _locate_error_stage(
    gold_sql: str,
    extracted_schema: dict,
    chosen_schema: dict,
    pruned: bool,
    try_times: int,
    fixed: bool,
) -> str:
    """Determine which pipeline stage caused the error."""
    gold_upper = _normalize_sql(gold_sql)
    gold_tables = _extract_tables(gold_upper)

    if pruned and extracted_schema:
        available_tables = set()
        for tbl, cols in extracted_schema.items():
            if cols != "drop_all":
                available_tables.add(tbl.upper())

        missing_tables = gold_tables - available_tables
        if missing_tables:
            return "selector"

    if try_times > 1 and not fixed:
        return "refiner"

    return "decomposer"


def load_and_analyze(
    eval_result_path: str,
    output_jsonl_path: str,
) -> list[AnalyzedError]:
    """Load evaluation results and output JSONL, produce analyzed errors."""

    with open(eval_result_path, "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    output_map: dict[int, dict] = {}
    with open(output_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            output_map[item["idx"]] = item

    results: list[AnalyzedError] = []

    for entry in eval_data:
        if entry["res"] == 1:
            continue

        qid = entry["question_id"]
        pred_sql = entry.get("pred", "")
        gold_sql = entry.get("gold", "")

        output_item = output_map.get(qid, {})
        extracted_schema = output_item.get("extracted_schema", {})
        chosen_schema = output_item.get("chosen_db_schem_dict", {})
        pruned = output_item.get("pruned", False)
        try_times = output_item.get("try_times", 0)
        fixed = output_item.get("fixed", False)

        error_stage = _locate_error_stage(
            gold_sql, extracted_schema, chosen_schema, pruned, try_times, fixed,
        )

        pred_upper = _normalize_sql(pred_sql)
        gold_upper = _normalize_sql(gold_sql)
        error_points = _classify_clause_errors(pred_upper, gold_upper)

        analyzed = AnalyzedError(
            question_id=qid,
            db_id=entry.get("db_id", ""),
            question=entry.get("question", ""),
            evidence=entry.get("evidence", ""),
            difficulty=entry.get("difficulty", ""),
            pred_sql=pred_sql,
            gold_sql=gold_sql,
            error_stage=error_stage,
            error_points=error_points,
            extracted_schema=extracted_schema,
            chosen_schema=chosen_schema,
            pruned=pruned,
            try_times=try_times,
            fixed=fixed,
        )
        results.append(analyzed)

    return results


def group_errors(
    analyzed: list[AnalyzedError],
) -> dict[tuple[str, str], list[AnalyzedError]]:
    """Group analyzed errors by (error_stage, primary_error_type)."""
    groups: dict[tuple[str, str], list[AnalyzedError]] = {}
    for a in analyzed:
        primary_types = {p.error_type for p in a.error_points if p.is_primary}
        if not primary_types:
            primary_types = {a.error_points[0].error_type} if a.error_points else {"semantic_mismatch"}
        for etype in primary_types:
            key = (a.error_stage, etype)
            groups.setdefault(key, []).append(a)
    return groups


def summarize_analysis(analyzed: list[AnalyzedError]) -> dict:
    """Produce a summary dict of the error analysis."""
    total = len(analyzed)
    by_stage: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}

    for a in analyzed:
        by_stage[a.error_stage] = by_stage.get(a.error_stage, 0) + 1
        by_difficulty[a.difficulty] = by_difficulty.get(a.difficulty, 0) + 1
        for p in a.error_points:
            if p.is_primary:
                by_type[p.error_type] = by_type.get(p.error_type, 0) + 1

    return {
        "total_errors": total,
        "by_stage": dict(sorted(by_stage.items(), key=lambda x: -x[1])),
        "by_primary_error_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_difficulty": dict(sorted(by_difficulty.items(), key=lambda x: -x[1])),
    }
