"""Proposer: call reasoning model to analyze error patterns and propose skills."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from .config import PROPOSER_MODEL, PROPOSER_API_BASE, API_KEY, SAMPLES_PER_GROUP
from .error_analyzer import AnalyzedError, ErrorPoint


@dataclass
class SkillProposal:
    name: str
    summary: str
    stage: str
    keywords: list[str]
    rules: str
    examples: str


PROPOSER_SYSTEM_PROMPT = """You are an expert SQL consultant specializing in text-to-SQL error analysis.

Your task: analyze a batch of text-to-SQL error cases that share a common error pattern, and propose ONE generalizable SQL writing strategy (skill) that would help avoid these errors.

STRICT RULES:
1. The strategy MUST be general — do NOT reference specific database names, table names, or column names.
2. Output the strategy as a concise list of rules (no more than 500 tokens total).
3. Include 1-2 positive/negative examples using placeholder names (e.g., table_A, column_X).
4. Specify which pipeline stage this strategy applies to: "selector", "decomposer", or "refiner".
5. Provide 3-5 lowercase keywords for matching.

You MUST respond with valid JSON in exactly this format:
{
  "name": "snake_case_skill_name",
  "summary": "One-sentence description",
  "stage": "decomposer",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "rules": "## Rules\\n\\n1. Rule one\\n2. Rule two\\n...",
  "examples": "## Examples\\n\\n❌ Bad: ...\\n✅ Good: ..."
}"""


MERGE_SYSTEM_PROMPT = """You are an expert at consolidating SQL writing guidelines.

Given a list of SQL skills that may overlap in topic, identify which ones should be merged.

Rules:
1. Only merge skills that cover the SAME topic (e.g., two skills both about JOIN strategies).
2. Do NOT merge skills from different topics.
3. If no merges are possible, return an empty list.

Respond with valid JSON:
{
  "merge_groups": [
    {
      "skills_to_merge": ["skill_name_1", "skill_name_2"],
      "merged_name": "new_merged_name",
      "merged_summary": "Combined summary",
      "merged_keywords": ["kw1", "kw2", "kw3"],
      "merged_rules": "## Rules\\n\\n1. ...\\n2. ...",
      "merged_examples": "## Examples\\n\\n..."
    }
  ]
}

If nothing should be merged, return: {"merge_groups": []}"""


def _build_error_prompt(
    errors: list[AnalyzedError],
    error_type: str,
    error_stage: str,
) -> str:
    samples = errors[:SAMPLES_PER_GROUP]
    parts = [
        f"Error pattern: stage={error_stage}, type={error_type}",
        f"Number of occurrences: {len(errors)}",
        "",
    ]
    for i, err in enumerate(samples, 1):
        primary_points = [p for p in err.error_points if p.is_primary and p.error_type == error_type]
        detail = primary_points[0].detail if primary_points else ""

        parts.append(f"--- Error Case {i} ---")
        parts.append(f"Question: {err.question}")
        if err.evidence:
            parts.append(f"Evidence: {err.evidence}")
        parts.append(f"Predicted SQL:\n{err.pred_sql}")
        parts.append(f"Gold SQL:\n{err.gold_sql}")
        parts.append(f"Error detail: {detail}")
        parts.append(f"Difficulty: {err.difficulty}")
        parts.append("")

    return "\n".join(parts)


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    max_retries: int = 3,
) -> str:
    model = model or PROPOSER_MODEL
    api_base = api_base or PROPOSER_API_BASE
    api_key = API_KEY or os.getenv("OPENAI_API_KEY", "")

    client = OpenAI(api_key=api_key, base_url=api_base)

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            content = resp.choices[0].message.content or ""
            if hasattr(resp.choices[0].message, "reasoning_content"):
                reasoning = resp.choices[0].message.reasoning_content
                if reasoning:
                    print(f"  [Reasoning preview] {reasoning[:200]}...")
            return content.strip()
        except Exception as e:
            print(f"  [WARN] LLM call failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"LLM call failed after {max_retries} retries")


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Failed to parse JSON from LLM response:\n{text[:500]}")


def propose_skill(
    errors: list[AnalyzedError],
    error_type: str,
    error_stage: str,
) -> Optional[SkillProposal]:
    """Call Proposer model to generate a skill proposal for a group of similar errors."""
    user_prompt = _build_error_prompt(errors, error_type, error_stage)
    print(f"  [Proposer] Analyzing {len(errors)} errors (stage={error_stage}, type={error_type})...")

    try:
        response = _call_llm(PROPOSER_SYSTEM_PROMPT, user_prompt)
        data = _parse_json_response(response)

        return SkillProposal(
            name=data.get("name", f"{error_stage}_{error_type}"),
            summary=data.get("summary", ""),
            stage=data.get("stage", error_stage),
            keywords=data.get("keywords", []),
            rules=data.get("rules", ""),
            examples=data.get("examples", ""),
        )
    except Exception as e:
        print(f"  [ERROR] Proposer failed for ({error_stage}, {error_type}): {e}")
        return None


def propose_merge(
    skills_info: list[dict],
    model: Optional[str] = None,
    api_base: Optional[str] = None,
) -> list[dict]:
    """Call LLM to suggest which skills should be merged."""
    from .config import MERGE_MODEL, GENERATOR_API_BASE
    model = model or MERGE_MODEL
    api_base = api_base or GENERATOR_API_BASE

    user_prompt = "Here are the current skills in one stage:\n\n"
    for info in skills_info:
        user_prompt += f"- **{info['name']}**: {info['summary']} (keywords: {', '.join(info['keywords'])})\n"
        user_prompt += f"  Rules preview: {info.get('rules_preview', '')[:200]}\n\n"

    try:
        response = _call_llm(MERGE_SYSTEM_PROMPT, user_prompt, model=model, api_base=api_base)
        data = _parse_json_response(response)
        return data.get("merge_groups", [])
    except Exception as e:
        print(f"  [WARN] Merge proposal failed: {e}")
        return []
