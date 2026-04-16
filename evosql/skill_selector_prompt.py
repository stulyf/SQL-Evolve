"""Prompt template for the LLM-based skill selector (Layer 2)."""

SKILL_SELECTOR_TEMPLATE = """\
You are a SQL strategy skill selector for a Text-to-SQL system.

Given a natural language question, database schema summary, and a registry of available skills,
select the most relevant skills that would help generate correct SQL.

【Question】
{question}

【Schema Summary】
{schema_summary}
{error_section}{prev_stage_section}
【Available Skills】
{registry_block}

Instructions:
- Return a JSON array of skill names (at most {max_select}), e.g.: ["skill_a", "skill_b"]
- Only select skills whose rules are directly relevant to this specific question.
- If no skill is relevant, return an empty array: []

【Selected Skills】
"""


def build_skill_selector_prompt(
    question: str,
    schema_summary: str,
    registry_block: str,
    max_select: int = 3,
    error_text: str = "",
    prev_stage_skills: list[str] | None = None,
) -> str:
    error_section = ""
    if error_text:
        error_section = f"\n【Error Context】\n{error_text}\n"

    prev_stage_section = ""
    if prev_stage_skills:
        names = ", ".join(prev_stage_skills)
        prev_stage_section = (
            f"\n【Already Applied Skills (avoid duplicates)】\n{names}\n"
        )

    return SKILL_SELECTOR_TEMPLATE.format(
        question=question,
        schema_summary=schema_summary,
        error_section=error_section,
        prev_stage_section=prev_stage_section,
        registry_block=registry_block,
        max_select=max_select,
    )
