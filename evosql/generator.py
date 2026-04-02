"""Generator: convert proposer output into SKILL.md files."""

from __future__ import annotations

from .proposer import SkillProposal
from .skill_manager import SkillManager, Skill


def generate_skill(
    proposal: SkillProposal,
    manager: SkillManager,
    round_id: str = "round_1",
) -> Skill:
    """Create a SKILL.md file from a SkillProposal and register it in the manager."""
    body_parts = []
    if proposal.rules:
        body_parts.append(proposal.rules)
    if proposal.examples:
        body_parts.append(proposal.examples)
    if not body_parts:
        body_parts.append("## Rules\n\n(No rules generated)")

    body = "\n\n".join(body_parts)

    skill = manager.create_skill(
        name=proposal.name,
        stage=proposal.stage,
        summary=proposal.summary,
        keywords=proposal.keywords,
        body=body,
        round_id=round_id,
    )
    return skill


def apply_merge(
    manager: SkillManager,
    merge_group: dict,
    round_id: str = "round_1",
) -> Skill:
    """Apply a merge proposal from the proposer's merge suggestion."""
    body_parts = []
    if merge_group.get("merged_rules"):
        body_parts.append(merge_group["merged_rules"])
    if merge_group.get("merged_examples"):
        body_parts.append(merge_group["merged_examples"])
    body = "\n\n".join(body_parts) if body_parts else "## Rules\n\n(merged)"

    return manager.merge_skills(
        names=merge_group["skills_to_merge"],
        merged_name=merge_group["merged_name"],
        merged_summary=merge_group["merged_summary"],
        merged_keywords=merge_group["merged_keywords"],
        merged_body=body,
        round_id=round_id,
    )
