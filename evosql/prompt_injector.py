"""Prompt injector: two-layer skill loading for SQLaxy prompt enhancement.

Dynamically selects relevant skills and injects them into prompt templates
during inference (Round 2+).
"""

from __future__ import annotations

import re
from pathlib import Path

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


def build_registry_block(manager: SkillManager, stage: str) -> str:
    """Build the lightweight registry index for a stage (~20-30 tokens/skill)."""
    skills = manager.skills_by_stage(stage)
    if not skills:
        return ""

    lines = [f"[Available {stage} skills]"]
    for i, s in enumerate(skills, 1):
        kws = ", ".join(s.keywords[:5])
        lines.append(f"{i}. {s.name}: {s.summary} | {kws}")
    return "\n".join(lines)


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
    """Select the most relevant skills for a given question.

    Filtering criteria:
      1. Keyword overlap >= MIN_OVERLAP_THRESHOLD (after removing stop words)
      2. Skill must be eligible (not proven harmful or ineffective)
      3. Sorted by overlap count (desc), then effectiveness (desc)
    """
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


def inject_skills_into_prompt(
    template: str,
    manager: SkillManager,
    stage: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    top_k: int = 2,
) -> str:
    """Inject relevant skills into a SQLaxy prompt template.

    Looks for the marker ``【SQL Strategy Skills】`` in the template.
    If present, replaces the entire marker line with the skill block.
    Otherwise, inserts before the first placeholder ``{...}``.
    """
    skills = select_relevant_skills(manager, stage, question, schema_text, error_text, top_k)
    if not skills:
        return template

    skill_block_parts = ["【SQL Strategy Skills — follow these learned patterns to avoid common errors】"]
    for skill in skills:
        skill_block_parts.append(f"\n### {skill.summary}\n")
        skill_block_parts.append(skill.body)
    skill_block = "\n".join(skill_block_parts)

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
