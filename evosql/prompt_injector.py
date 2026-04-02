"""Prompt injector: two-layer skill loading for SQLaxy prompt enhancement.

Used in Round 2+ when re-running SQLaxy with skills injected into prompts.
"""

from __future__ import annotations

import re
from pathlib import Path

from .skill_manager import SkillManager, Skill
from .skill_matcher import _tokenize_text


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


def select_relevant_skills(
    manager: SkillManager,
    stage: str,
    question: str,
    schema_text: str = "",
    error_text: str = "",
    top_k: int = 2,
) -> list[Skill]:
    """Select the most relevant skills for a given question via keyword matching."""
    candidates = manager.skills_by_stage(stage)
    if not candidates:
        return []

    query_tokens = set()
    query_tokens.update(_tokenize_text(question))
    query_tokens.update(_tokenize_text(schema_text))
    if error_text:
        query_tokens.update(_tokenize_text(error_text))

    scored: list[tuple[Skill, int, float]] = []
    for skill in candidates:
        skill_kws = set(k.lower() for k in skill.keywords)
        overlap_count = len(query_tokens & skill_kws)
        if overlap_count >= 1:
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

    Inserts a skill block before the first placeholder (e.g., {desc_str})
    so the LLM sees the strategy guidance before the actual task.
    """
    skills = select_relevant_skills(manager, stage, question, schema_text, error_text, top_k)
    if not skills:
        return template

    skill_block_parts = ["【SQL Strategy Skills】"]
    for skill in skills:
        skill_block_parts.append(f"\n### {skill.summary}\n")
        skill_block_parts.append(skill.body)
    skill_block = "\n".join(skill_block_parts) + "\n\n"

    first_placeholder = re.search(r"\{[a-z_]+\}", template)
    if first_placeholder:
        pos = first_placeholder.start()
        return template[:pos] + skill_block + template[pos:]

    return skill_block + template


def get_enhanced_templates(
    manager: SkillManager,
    question: str,
    evidence: str = "",
    desc_str: str = "",
) -> dict[str, str]:
    """Return enhanced prompt templates for all three stages.

    This is a convenience function for Round 2 integration.
    """
    from core.const import selector_template, decompose_template_bird, refiner_template

    schema_text = f"{question} {evidence} {desc_str}"

    return {
        "selector": inject_skills_into_prompt(
            selector_template, manager, "selector", question, schema_text,
        ),
        "decomposer": inject_skills_into_prompt(
            decompose_template_bird, manager, "decomposer", question, schema_text,
        ),
        "refiner": inject_skills_into_prompt(
            refiner_template, manager, "refiner", question, schema_text,
        ),
    }
