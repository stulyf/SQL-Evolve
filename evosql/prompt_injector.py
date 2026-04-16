"""Prompt injector: progressive skill injection for SQLaxy prompt enhancement.

Supports two modes controlled by config.USE_PROGRESSIVE_INJECTION:
  - Legacy mode (default): keyword-overlap matching + direct full-text injection
  - Progressive mode: 3-layer injection (registry index → LLM selection → budget-aware injection)
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from .skill_manager import SkillManager, Skill
from .skill_matcher import _tokenize_text

STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "of", "in", "to", "for",
    "with", "on", "at", "by", "from", "as", "into", "about", "between",
    "through", "after", "before", "above", "below", "and", "or", "not",
    "but", "if", "then", "else", "when", "while", "where", "how", "what",
    "which", "who", "whom", "this", "that", "these", "those", "it", "its",
    "all", "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "only", "same", "so", "than", "too", "very",
    "select", "from", "table", "column", "value", "query", "database",
})

MIN_OVERLAP_THRESHOLD = 2
MIN_EFFECTIVENESS_FOR_ESTABLISHED = 0.3
MIN_MATCHES_TO_JUDGE = 5

CHARS_PER_TOKEN_ESTIMATE = 4


# ---------------------------------------------------------------------------
# Layer 1: Registry Index
# ---------------------------------------------------------------------------

def build_registry_block(manager: SkillManager, stage: str) -> str:
    """Build the lightweight registry index for a stage (~20-30 tokens/skill).

    Only includes eligible skills (not proven harmful / ineffective).
    """
    skills = manager.skills_by_stage(stage)
    if not skills:
        return ""

    eligible = [s for s in skills if _is_skill_eligible(s)]
    if not eligible:
        return ""

    lines = [f"[Available {stage} skills]"]
    for i, s in enumerate(eligible, 1):
        kws = ", ".join(s.keywords[:5])
        lines.append(f"{i}. {s.name}: {s.summary} | {kws}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Layer 2: LLM-based Skill Selection
# ---------------------------------------------------------------------------

def select_skills_via_llm(
    registry_block: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    context_from_prev_stage: Optional[dict] = None,
    max_select: int = 3,
) -> list[str]:
    """Use a lightweight LLM call to pick the most relevant skills from the registry.

    Returns a list of skill names (strings).
    """
    from .skill_selector_prompt import build_skill_selector_prompt
    from . import config

    prev_skills: list[str] = []
    if context_from_prev_stage:
        prev_skills = context_from_prev_stage.get("selected_skills", [])

    schema_summary = schema_text[:600] if schema_text else ""

    prompt = build_skill_selector_prompt(
        question=question,
        schema_summary=schema_summary,
        registry_block=registry_block,
        max_select=max_select,
        error_text=error_text,
        prev_stage_skills=prev_skills if prev_skills else None,
    )

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    llm = ChatOpenAI(
        model=config.SKILL_SELECTOR_MODEL,
        base_url=config.SKILL_SELECTOR_API_BASE,
        api_key=config.API_KEY or os.getenv("OPENAI_API_KEY", ""),
        temperature=0.0,
        max_tokens=200,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        text = (response.content or "").strip()
        selected = _parse_skill_names(text, max_select)
        print(f"  [SkillSelector] LLM selected: {selected}", flush=True)
        return selected
    except Exception as e:
        print(f"  [SkillSelector] LLM call failed ({e}), falling back to empty", flush=True)
        return []


def _parse_skill_names(text: str, max_select: int) -> list[str]:
    """Extract a JSON array of skill names from LLM output, tolerant of formatting."""
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
        if isinstance(parsed, list):
            return [str(n).strip() for n in parsed if isinstance(n, str)][:max_select]
    except json.JSONDecodeError:
        pass
    return []


# ---------------------------------------------------------------------------
# Layer 3: Budget-aware Full Injection
# ---------------------------------------------------------------------------

def inject_with_budget(
    template: str,
    manager: SkillManager,
    selected_names: list[str],
    token_budget: int,
) -> str:
    """Inject selected skills' full body into the prompt template,
    respecting a token budget. Skills exceeding the budget are reduced
    to summary-only.
    """
    if not selected_names:
        return template

    skills = [manager.get_skill(n) for n in selected_names]
    skills = [s for s in skills if s is not None]
    if not skills:
        return template

    skills.sort(key=lambda s: -s.stats.effectiveness)

    char_budget = token_budget * CHARS_PER_TOKEN_ESTIMATE
    used_chars = 0

    skill_block_parts = [
        "【SQL Strategy Skills — follow these learned patterns to avoid common errors】"
    ]

    for skill in skills:
        full_entry = f"\n### {skill.summary}\n{skill.body}"
        summary_entry = f"\n### {skill.summary}\n(Skill content omitted due to budget)"

        if used_chars + len(full_entry) <= char_budget:
            skill_block_parts.append(full_entry)
            used_chars += len(full_entry)
        elif used_chars + len(summary_entry) <= char_budget:
            skill_block_parts.append(summary_entry)
            used_chars += len(summary_entry)
        else:
            break

    if len(skill_block_parts) <= 1:
        return template

    skill_block = "\n".join(skill_block_parts)
    return _insert_skill_block(template, skill_block)


def _insert_skill_block(template: str, skill_block: str) -> str:
    """Insert a skill block into a prompt template at the canonical position."""
    marker = "【SQL Strategy Skills"
    marker_pos = template.find(marker)
    if marker_pos != -1:
        marker_end = template.find("\n\n", marker_pos)
        if marker_end == -1:
            marker_end = len(template)
        else:
            marker_end += 1
        return template[:marker_pos] + skill_block + "\n" + template[marker_end:]

    first_placeholder = re.search(r"\{[a-z_]+\}", template)
    if first_placeholder:
        pos = first_placeholder.start()
        return template[:pos] + skill_block + "\n\n" + template[pos:]

    return skill_block + "\n\n" + template


# ---------------------------------------------------------------------------
# Progressive injection entry point (new API)
# ---------------------------------------------------------------------------

def inject_skills_progressive(
    template: str,
    manager: SkillManager,
    stage: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    max_skills: int | None = None,
    token_budget: int | None = None,
    context_from_prev_stage: Optional[dict] = None,
) -> tuple[str, dict]:
    """Three-layer progressive skill injection.

    Layer 1: Build lightweight registry index
    Layer 2: LLM selects relevant skills from registry
    Layer 3: Inject selected skills' full text within token budget

    Returns (injected_template, stage_context_dict).
    """
    from . import config

    if max_skills is None:
        max_skills = config.SKILL_MAX_INJECT.get(stage, 2)
    if token_budget is None:
        token_budget = config.SKILL_TOKEN_BUDGET

    # Layer 1
    registry = build_registry_block(manager, stage)
    if not registry:
        return template, {}

    # Layer 2
    selected_names = select_skills_via_llm(
        registry, question, schema_text, error_text,
        context_from_prev_stage,
        max_select=max_skills,
    )

    if not selected_names:
        return template, {}

    # Layer 3
    result_template = inject_with_budget(
        template, manager, selected_names, token_budget,
    )

    prev_skills = []
    if context_from_prev_stage:
        prev_skills = list(context_from_prev_stage.get("selected_skills", []))
    prev_skills.extend(selected_names)

    stage_context = {
        "selected_skills": prev_skills,
        "stage": stage,
    }
    return result_template, stage_context


# ---------------------------------------------------------------------------
# Legacy API (backward-compatible)
# ---------------------------------------------------------------------------

def _is_skill_eligible(skill: Skill) -> bool:
    """Check if a skill has enough evidence of being helpful (or is still new)."""
    if skill.stats.match_count < MIN_MATCHES_TO_JUDGE:
        return True
    if skill.stats.effectiveness < MIN_EFFECTIVENESS_FOR_ESTABLISHED:
        return False
    if skill.stats.harm_ratio > 0.3:
        return False
    return True


def select_relevant_skills(
    manager: SkillManager,
    stage: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    top_k: int = 2,
) -> list[Skill]:
    """Legacy keyword-overlap skill selection (no LLM cost)."""
    candidates = manager.skills_by_stage(stage)
    if not candidates:
        return []

    query_tokens = set()
    query_tokens.update(_tokenize_text(question))
    query_tokens.update(_tokenize_text(schema_text))
    if error_text:
        query_tokens.update(_tokenize_text(error_text))
    query_tokens -= STOP_WORDS

    scored: list[tuple[Skill, int, float]] = []
    for skill in candidates:
        if not _is_skill_eligible(skill):
            continue
        skill_kws = set(k.lower() for k in skill.keywords) - STOP_WORDS
        overlap_count = len(query_tokens & skill_kws)
        if overlap_count >= MIN_OVERLAP_THRESHOLD:
            scored.append((skill, overlap_count, skill.stats.effectiveness))

    scored.sort(key=lambda x: (-x[1], -x[2]))
    return [s for s, _, _ in scored[:top_k]]


def _inject_skills_legacy(
    template: str,
    manager: SkillManager,
    stage: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    top_k: int = 2,
) -> str:
    """Original injection logic: keyword match → full-text paste."""
    skills = select_relevant_skills(manager, stage, question, schema_text, error_text, top_k)
    if not skills:
        return template

    skill_block_parts = [
        "【SQL Strategy Skills — follow these learned patterns to avoid common errors】"
    ]
    for skill in skills:
        skill_block_parts.append(f"\n### {skill.summary}\n")
        skill_block_parts.append(skill.body)
    skill_block = "\n".join(skill_block_parts)

    return _insert_skill_block(template, skill_block)


def inject_skills_into_prompt(
    template: str,
    manager: SkillManager,
    stage: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    top_k: int = 2,
) -> str:
    """Public API — dispatches to progressive or legacy mode.

    When USE_PROGRESSIVE_INJECTION is enabled, uses the three-layer pipeline.
    Otherwise falls back to legacy keyword-overlap injection.

    This wrapper discards the stage_context returned by progressive mode
    to keep the same return signature. For full progressive support with
    inter-stage context, call inject_skills_progressive() directly.
    """
    from . import config

    if config.USE_PROGRESSIVE_INJECTION:
        result, _ = inject_skills_progressive(
            template, manager, stage, question,
            schema_text=schema_text,
            error_text=error_text,
            max_skills=top_k,
        )
        return result

    return _inject_skills_legacy(
        template, manager, stage, question,
        schema_text, error_text, top_k,
    )
