"""Main runner: orchestrates offline error analysis, skill construction, and feedback."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import MERGE_THRESHOLD, SKILL_LIMITS, STAGES
from .error_analyzer import load_and_analyze, group_errors, summarize_analysis
from .skill_manager import SkillManager
from .skill_matcher import match_all_errors
from .proposer import propose_skill, propose_merge
from .generator import generate_skill, apply_merge
from .feedback import collect_feedback, print_feedback_report


def _log(phase: str, msg: str = "") -> None:
    print(f"\n[{phase}] {msg}", flush=True)


def run_round1(
    eval_result_path: str,
    output_jsonl_path: str,
    skill_dir: str,
    merge_threshold: int = MERGE_THRESHOLD,
    dry_run: bool = False,
) -> None:
    """Execute Round 1: offline error analysis → skill construction."""

    _log("INIT", "Starting EvoSQL Round 1 (offline skill construction)")
    _log("INIT", f"  eval_result: {eval_result_path}")
    _log("INIT", f"  output_jsonl: {output_jsonl_path}")
    _log("INIT", f"  skill_dir: {skill_dir}")
    _log("INIT", f"  merge_threshold: {merge_threshold}")
    _log("INIT", f"  dry_run: {dry_run}")

    # ---- Step 1: Error Analysis ----
    _log("STEP 1", "Analyzing errors...")
    analyzed = load_and_analyze(eval_result_path, output_jsonl_path)
    summary = summarize_analysis(analyzed)
    _log("STEP 1", f"  Total errors: {summary['total_errors']}")
    _log("STEP 1", f"  By stage: {summary['by_stage']}")
    _log("STEP 1", f"  By primary type: {summary['by_primary_error_type']}")
    _log("STEP 1", f"  By difficulty: {summary['by_difficulty']}")

    # ---- Step 2: Initialize Skill Manager ----
    _log("STEP 2", "Initializing skill manager...")
    manager = SkillManager(skill_dir)
    existing = manager.all_skills()
    if existing:
        _log("STEP 2", f"  Loaded {len(existing)} existing skills")
    else:
        _log("STEP 2", "  Starting with empty skill library")

    # ---- Step 3: Match errors against existing skills ----
    _log("STEP 3", "Matching errors against skill library...")
    matched, unmatched = match_all_errors(analyzed, manager)
    _log("STEP 3", f"  Matched: {len(matched)} error points")
    _log("STEP 3", f"  Unmatched: {len(unmatched)} error points (need new skills)")

    # ---- Step 4: Group unmatched errors ----
    _log("STEP 4", "Grouping unmatched errors by (stage, error_type)...")
    unmatched_errors_by_type: dict[tuple[str, str], list] = {}
    for error, ep in unmatched:
        key = (error.error_stage, ep.error_type)
        unmatched_errors_by_type.setdefault(key, []).append(error)

    _log("STEP 4", f"  Found {len(unmatched_errors_by_type)} distinct error pattern groups:")
    for (stage, etype), errors in sorted(unmatched_errors_by_type.items(), key=lambda x: -len(x[1])):
        _log("", f"    ({stage}, {etype}): {len(errors)} errors")

    if dry_run:
        _log("DRY RUN", "Stopping before LLM calls. Error analysis complete.")
        report_path = Path(skill_dir) / "error_analysis_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = {
            "summary": summary,
            "groups": {f"{s}_{t}": len(e) for (s, t), e in unmatched_errors_by_type.items()},
        }
        report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
        _log("DRY RUN", f"  Report saved to {report_path}")
        return

    # ---- Step 5: Call Proposer for each group ----
    _log("STEP 5", "Calling Proposer to generate skill proposals...")
    total_groups = len(unmatched_errors_by_type)
    created_count = 0
    skills_created_this_round: list[str] = []

    MIN_GROUP_SIZE = 3
    groups_to_process = {
        k: v for k, v in unmatched_errors_by_type.items() if len(v) >= MIN_GROUP_SIZE
    }
    skipped = len(unmatched_errors_by_type) - len(groups_to_process)
    if skipped:
        _log("STEP 5", f"  Skipping {skipped} groups with < {MIN_GROUP_SIZE} errors")
    total_groups = len(groups_to_process)

    for i, ((stage, etype), errors) in enumerate(
        sorted(groups_to_process.items(), key=lambda x: -len(x[1])), 1
    ):
        _log("STEP 5", f"  [{i}/{total_groups}] Processing ({stage}, {etype}) — {len(errors)} errors")

        proposal = propose_skill(errors, etype, stage)
        if proposal is None:
            _log("", f"    [SKIP] Proposer returned no proposal")
            continue

        _log("", f"    Proposed: {proposal.name} ({proposal.stage}) — {proposal.summary[:80]}")

        skill = generate_skill(proposal, manager, round_id="round_1")
        skills_created_this_round.append(skill.name)
        created_count += 1
        _log("", f"    Created: {skill.name}")

        # ---- Step 6: Check merge threshold ----
        stages_needing_merge = manager.check_merge_needed(merge_threshold)
        for merge_stage in stages_needing_merge:
            _log("MERGE", f"  Merge threshold reached for {merge_stage}, running merge review...")
            _run_merge(manager, merge_stage)
            manager.reset_merge_counter(merge_stage)

        time.sleep(1)

    _log("STEP 5", f"  Created {created_count} new skills")

    # ---- Step 7: Final elimination ----
    _log("STEP 7", "Running final elimination check...")
    eliminated = manager.eliminate()
    if eliminated:
        _log("STEP 7", f"  Eliminated {len(eliminated)} skills: {eliminated}")
    else:
        _log("STEP 7", "  No skills eliminated (all within limits)")

    # ---- Step 8: Report ----
    _log("DONE", "Round 1 complete!")
    report = manager.export_report()
    print("\n" + report)

    report_path = Path(skill_dir) / "round1_report.txt"
    report_path.write_text(report, encoding="utf-8")
    _log("DONE", f"  Report saved to {report_path}")


def _run_merge(manager: SkillManager, stage: str) -> None:
    """Run merge review for a specific stage."""
    skills = manager.skills_by_stage(stage)
    if len(skills) < 2:
        return

    skills_info = []
    for s in skills:
        skills_info.append({
            "name": s.name,
            "summary": s.summary,
            "keywords": s.keywords,
            "rules_preview": s.body[:300],
        })

    merge_groups = propose_merge(skills_info)
    if not merge_groups:
        _log("MERGE", f"    No merges suggested for {stage}")
        return

    for group in merge_groups:
        names = group.get("skills_to_merge", [])
        valid_names = [n for n in names if manager.get_skill(n)]
        if len(valid_names) < 2:
            continue
        merged = apply_merge(manager, group, round_id="round_1")
        _log("MERGE", f"    Merged {valid_names} → {merged.name}")


def run_feedback(
    baseline_eval_path: str,
    enhanced_eval_path: str,
    enhanced_output_path: str,
    skill_dir: str,
    round_id: str = "round_2",
) -> None:
    """Execute feedback collection: compare baseline vs enhanced, update skill stats."""
    _log("FEEDBACK", "Starting feedback collection")
    _log("FEEDBACK", f"  baseline_eval: {baseline_eval_path}")
    _log("FEEDBACK", f"  enhanced_eval: {enhanced_eval_path}")
    _log("FEEDBACK", f"  enhanced_output: {enhanced_output_path}")
    _log("FEEDBACK", f"  skill_dir: {skill_dir}")
    _log("FEEDBACK", f"  round_id: {round_id}")

    manager = SkillManager(skill_dir)
    _log("FEEDBACK", f"  Loaded {len(manager.all_skills())} skills")

    stats = collect_feedback(
        baseline_eval_path=baseline_eval_path,
        enhanced_eval_path=enhanced_eval_path,
        enhanced_output_path=enhanced_output_path,
        manager=manager,
        round_id=round_id,
    )

    report = print_feedback_report(stats)
    report_path = Path(skill_dir) / f"{round_id}_feedback_report.txt"
    report_path.write_text(report, encoding="utf-8")
    _log("FEEDBACK", f"  Report saved to {report_path}")

    eliminated = manager.eliminate()
    if eliminated:
        _log("FEEDBACK", f"  Eliminated {len(eliminated)} low-performing skills: {eliminated}")

    _log("FEEDBACK", "Feedback collection complete!")
    print("\n" + manager.export_report())


def main() -> None:
    parser = argparse.ArgumentParser(description="EvoSQL: offline skill construction and feedback")
    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    p_round1 = subparsers.add_parser("round1", help="Round 1: error analysis + skill generation")
    p_round1.add_argument("--eval-result", required=True, help="Path to eval_result_dev.json")
    p_round1.add_argument("--output-jsonl", required=True, help="Path to output_bird.json (JSONL)")
    p_round1.add_argument("--skill-dir", default="./evosql/skills", help="Directory to store generated skills")
    p_round1.add_argument("--merge-threshold", type=int, default=MERGE_THRESHOLD,
                          help=f"New skills before triggering merge (default: {MERGE_THRESHOLD})")
    p_round1.add_argument("--dry-run", action="store_true", help="Only run error analysis, skip LLM calls")

    p_feedback = subparsers.add_parser("feedback", help="Collect feedback from enhanced run")
    p_feedback.add_argument("--baseline-eval", required=True, help="Path to baseline eval_result_dev.json")
    p_feedback.add_argument("--enhanced-eval", required=True, help="Path to enhanced eval_result_dev.json")
    p_feedback.add_argument("--enhanced-output", required=True, help="Path to enhanced output_bird.json (JSONL)")
    p_feedback.add_argument("--skill-dir", default="./evosql/skills", help="Directory with skill files")
    p_feedback.add_argument("--round-id", default="round_2", help="Round identifier (default: round_2)")

    args = parser.parse_args()

    if args.command == "round1" or args.command is None:
        if args.command is None:
            parser.print_help()
            sys.exit(1)
        run_round1(
            eval_result_path=args.eval_result,
            output_jsonl_path=args.output_jsonl,
            skill_dir=args.skill_dir,
            merge_threshold=args.merge_threshold,
            dry_run=args.dry_run,
        )
    elif args.command == "feedback":
        run_feedback(
            baseline_eval_path=args.baseline_eval,
            enhanced_eval_path=args.enhanced_eval,
            enhanced_output_path=args.enhanced_output,
            skill_dir=args.skill_dir,
            round_id=args.round_id,
        )


if __name__ == "__main__":
    main()
