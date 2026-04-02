"""Skill matcher: zero-LLM-cost keyword/rule matching with priority sorting."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .error_analyzer import ErrorPoint, AnalyzedError
from .skill_manager import Skill, SkillManager


@dataclass
class MatchResult:
    skill_name: str
    skill_stage: str
    matched_keywords: list[str]
    effectiveness: float
    score: float


def _tokenize_text(text: str) -> set[str]:
    """Extract lowercase tokens from text for keyword matching."""
    return set(re.findall(r"[a-z_]{2,}", text.lower()))


def match_error_to_skills(
    error: AnalyzedError,
    error_point: ErrorPoint,
    manager: SkillManager,
    top_k: int = 2,
) -> list[MatchResult]:
    """Match a single error point against the skill library.

    Returns up to top_k matching skills sorted by priority:
      1. keyword overlap count (desc)
      2. effectiveness (desc)
    """
    stage = error.error_stage
    candidates = manager.skills_by_stage(stage)
    if not candidates:
        return []

    query_tokens = set()
    query_tokens.update(_tokenize_text(error.question))
    query_tokens.update(_tokenize_text(error.pred_sql))
    query_tokens.update(_tokenize_text(error.gold_sql))
    query_tokens.update(_tokenize_text(error_point.error_type))
    query_tokens.update(_tokenize_text(error_point.detail))

    SQL_KEYWORDS = {
        "wrong_table": {"from", "table", "join", "schema"},
        "wrong_join": {"join", "inner", "left", "foreign", "key", "on"},
        "wrong_aggregation": {"count", "sum", "avg", "max", "min", "group", "having"},
        "wrong_filter": {"where", "filter", "condition", "and", "or", "between", "like"},
        "wrong_subquery": {"subquery", "select", "nested", "exists", "in"},
        "wrong_order": {"order", "limit", "asc", "desc", "top", "rank"},
        "wrong_select": {"select", "column", "alias", "distinct"},
        "semantic_mismatch": {"semantic", "meaning", "intent", "interpretation"},
        "syntax_error": {"syntax", "parse", "error"},
        "type_error": {"cast", "type", "integer", "real", "text", "convert"},
        "no_such_table": {"table", "schema", "from"},
        "no_such_column": {"column", "field", "attribute"},
    }
    extra_kws = SQL_KEYWORDS.get(error_point.error_type, set())
    query_tokens.update(extra_kws)

    matches: list[MatchResult] = []
    for skill in candidates:
        skill_kws = set(k.lower() for k in skill.keywords)
        overlap = query_tokens & skill_kws
        if len(overlap) >= 2:
            matches.append(MatchResult(
                skill_name=skill.name,
                skill_stage=skill.stage,
                matched_keywords=sorted(overlap),
                effectiveness=skill.stats.effectiveness,
                score=skill.stats.score,
            ))

    matches.sort(key=lambda m: (-len(m.matched_keywords), -m.effectiveness))
    return matches[:top_k]


def match_all_errors(
    errors: list[AnalyzedError],
    manager: SkillManager,
) -> tuple[list[tuple[AnalyzedError, ErrorPoint, list[MatchResult]]], list[tuple[AnalyzedError, ErrorPoint]]]:
    """Match all error points. Returns (matched, unmatched) lists."""
    matched: list[tuple[AnalyzedError, ErrorPoint, list[MatchResult]]] = []
    unmatched: list[tuple[AnalyzedError, ErrorPoint]] = []

    for error in errors:
        for ep in error.error_points:
            if not ep.is_primary:
                continue
            results = match_error_to_skills(error, ep, manager)
            if results:
                matched.append((error, ep, results))
                for r in results:
                    manager.update_stats(r.skill_name, match_delta=1)
            else:
                unmatched.append((error, ep))

    return matched, unmatched
