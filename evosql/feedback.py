"""Feedback loop: compare baseline vs skill-enhanced results and update skill stats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .skill_manager import SkillManager
from .prompt_injector import select_relevant_skills


def collect_feedback(
    baseline_eval_path: str,
    enhanced_eval_path: str,
    enhanced_output_path: str,
    manager: SkillManager,
    round_id: str = "round_2",
) -> dict:
    """Compare baseline and enhanced eval results, update skill help/harm counts.

    For each question:
      - If baseline wrong → enhanced correct: every injected skill gets help_count += 1
      - If baseline correct → enhanced wrong: every injected skill gets harm_count += 1
      - match_count += 1 for all injected skills regardless

    Returns a summary dict.
    """
    with open(baseline_eval_path, "r", encoding="utf-8") as f:
        baseline_eval = json.load(f)
    with open(enhanced_eval_path, "r", encoding="utf-8") as f:
        enhanced_eval = json.load(f)

    baseline_by_qid = {e["question_id"]: e["res"] for e in baseline_eval}

    enhanced_output: dict[int, dict] = {}
    with open(enhanced_output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            enhanced_output[item["idx"]] = item

    stats = {
        "total_questions": 0,
        "helped": 0,
        "harmed": 0,
        "neutral": 0,
        "skill_updates": {},
    }

    for entry in enhanced_eval:
        qid = entry["question_id"]
        enhanced_res = entry["res"]
        baseline_res = baseline_by_qid.get(qid)
        if baseline_res is None:
            continue

        stats["total_questions"] += 1

        output_item = enhanced_output.get(qid, {})
        question = output_item.get("query", "")
        evidence = output_item.get("evidence", "")
        schema_text = f"{question} {evidence}"

        injected_skills: set[str] = set()
        for stage in ["selector", "decomposer", "refiner"]:
            matched = select_relevant_skills(
                manager, stage, question, schema_text=schema_text
            )
            for skill in matched:
                injected_skills.add(skill.name)

        if not injected_skills:
            continue

        if baseline_res == 0 and enhanced_res == 1:
            stats["helped"] += 1
            for name in injected_skills:
                manager.update_stats(name, match_delta=1, help_delta=1)
                stats["skill_updates"][name] = stats["skill_updates"].get(name, {"help": 0, "harm": 0, "match": 0})
                stats["skill_updates"][name]["help"] += 1
                stats["skill_updates"][name]["match"] += 1
        elif baseline_res == 1 and enhanced_res == 0:
            stats["harmed"] += 1
            for name in injected_skills:
                manager.update_stats(name, match_delta=1, harm_delta=1)
                stats["skill_updates"][name] = stats["skill_updates"].get(name, {"help": 0, "harm": 0, "match": 0})
                stats["skill_updates"][name]["harm"] += 1
                stats["skill_updates"][name]["match"] += 1
        else:
            stats["neutral"] += 1
            for name in injected_skills:
                manager.update_stats(name, match_delta=1)
                stats["skill_updates"][name] = stats["skill_updates"].get(name, {"help": 0, "harm": 0, "match": 0})
                stats["skill_updates"][name]["match"] += 1

    manager.close_round(round_id)

    return stats


def print_feedback_report(stats: dict) -> str:
    lines = [
        "=" * 60,
        "Feedback Report",
        "=" * 60,
        f"Total questions compared: {stats['total_questions']}",
        f"  Helped (wrong→correct): {stats['helped']}",
        f"  Harmed (correct→wrong): {stats['harmed']}",
        f"  Neutral (no change):    {stats['neutral']}",
        "",
        "Per-skill updates:",
    ]
    for name, updates in sorted(stats["skill_updates"].items(), key=lambda x: -x[1].get("help", 0)):
        lines.append(
            f"  [{name}] match={updates['match']} help={updates['help']} harm={updates['harm']}"
        )
    lines.append("=" * 60)
    report = "\n".join(lines)
    print(report)
    return report
