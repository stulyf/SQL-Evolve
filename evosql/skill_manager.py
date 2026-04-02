"""Skill library manager: CRUD, stats tracking, merge, eliminate."""

from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class SkillStats:
    match_count: int = 0
    help_count: int = 0
    harm_count: int = 0
    match_history: list[int] = field(default_factory=list)
    help_history: list[int] = field(default_factory=list)
    harm_history: list[int] = field(default_factory=list)

    @property
    def effectiveness(self) -> float:
        if self.match_count == 0:
            return 0.0
        return self.help_count / self.match_count

    @property
    def harm_ratio(self) -> float:
        if self.help_count == 0:
            return 0.0 if self.harm_count == 0 else 1.0
        return self.harm_count / self.help_count

    @property
    def score(self) -> float:
        return self.effectiveness * math.log(1 + self.match_count)


@dataclass
class Skill:
    name: str
    summary: str
    keywords: list[str]
    stage: str
    body: str
    created_at: str = "round_1"
    last_updated: str = "round_1"
    stats: SkillStats = field(default_factory=SkillStats)
    priority: str = "medium"

    def to_yaml_header(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "keywords": self.keywords,
            "stage": self.stage,
            "priority": self.priority,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "stats": {
                "match_count": self.stats.match_count,
                "help_count": self.stats.help_count,
                "harm_count": self.stats.harm_count,
                "effectiveness": round(self.stats.effectiveness, 3),
                "harm_ratio": round(self.stats.harm_ratio, 3),
                "score": round(self.stats.score, 3),
                "match_history": self.stats.match_history,
                "help_history": self.stats.help_history,
                "harm_history": self.stats.harm_history,
            },
        }

    def to_markdown(self) -> str:
        header = yaml.dump(self.to_yaml_header(), default_flow_style=False, allow_unicode=True)
        return f"---\n{header}---\n\n{self.body}\n"

    def registry_entry(self) -> str:
        kws = ", ".join(self.keywords[:5])
        return f"{self.name}: {self.summary} | {kws}"

    @staticmethod
    def from_file(path: Path) -> "Skill":
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid SKILL.md format in {path}")
        header = yaml.safe_load(parts[1])
        body = parts[2].strip()

        stats_raw = header.get("stats", {})
        stats = SkillStats(
            match_count=stats_raw.get("match_count", 0),
            help_count=stats_raw.get("help_count", 0),
            harm_count=stats_raw.get("harm_count", 0),
            match_history=stats_raw.get("match_history", []),
            help_history=stats_raw.get("help_history", []),
            harm_history=stats_raw.get("harm_history", []),
        )

        return Skill(
            name=header["name"],
            summary=header.get("summary", ""),
            keywords=header.get("keywords", []),
            stage=header.get("stage", "decomposer"),
            body=body,
            created_at=header.get("created_at", "round_1"),
            last_updated=header.get("last_updated", "round_1"),
            stats=stats,
            priority=header.get("priority", "medium"),
        )


class SkillManager:
    """Manages the skill library on disk."""

    def __init__(self, skill_dir: str | Path, limits: dict[str, int] | None = None):
        self.skill_dir = Path(skill_dir)
        self.skill_dir.mkdir(parents=True, exist_ok=True)

        from .config import SKILL_LIMITS
        self.limits = limits or SKILL_LIMITS

        for stage in self.limits:
            (self.skill_dir / stage).mkdir(parents=True, exist_ok=True)

        self._skills: dict[str, Skill] = {}
        self._new_count_since_merge: dict[str, int] = {s: 0 for s in self.limits}
        self.reload()

    def reload(self) -> None:
        self._skills.clear()
        for stage_dir in self.skill_dir.iterdir():
            if not stage_dir.is_dir() or stage_dir.name.startswith("."):
                continue
            for skill_file in stage_dir.glob("*.md"):
                try:
                    skill = Skill.from_file(skill_file)
                    self._skills[skill.name] = skill
                except Exception as e:
                    print(f"[WARN] Failed to load {skill_file}: {e}")

    def _skill_path(self, skill: Skill) -> Path:
        return self.skill_dir / skill.stage / f"{skill.name}.md"

    def _save_skill(self, skill: Skill) -> None:
        path = self._skill_path(skill)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(skill.to_markdown(), encoding="utf-8")

    def create_skill(
        self,
        name: str,
        stage: str,
        summary: str,
        keywords: list[str],
        body: str,
        round_id: str = "round_1",
    ) -> Skill:
        name = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
        if name in self._skills:
            name = f"{name}_{len(self._skills)}"

        skill = Skill(
            name=name,
            summary=summary,
            keywords=[k.lower() for k in keywords],
            stage=stage,
            body=body,
            created_at=round_id,
            last_updated=round_id,
        )
        self._skills[name] = skill
        self._save_skill(skill)
        self._new_count_since_merge[stage] = self._new_count_since_merge.get(stage, 0) + 1
        return skill

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def skills_by_stage(self, stage: str) -> list[Skill]:
        return [s for s in self._skills.values() if s.stage == stage]

    def get_registry(self) -> dict[str, list[str]]:
        """Return per-stage registries (lightweight index)."""
        registry: dict[str, list[str]] = {}
        for stage in self.limits:
            registry[stage] = [s.registry_entry() for s in self.skills_by_stage(stage)]
        return registry

    def update_stats(
        self, name: str, match_delta: int = 0, help_delta: int = 0, harm_delta: int = 0,
    ) -> None:
        skill = self._skills.get(name)
        if not skill:
            return
        skill.stats.match_count += match_delta
        skill.stats.help_count += help_delta
        skill.stats.harm_count += harm_delta
        self._save_skill(skill)

    def close_round(self, round_id: str) -> None:
        """Snapshot current counts into history at end of a round."""
        for skill in self._skills.values():
            skill.stats.match_history.append(skill.stats.match_count)
            skill.stats.help_history.append(skill.stats.help_count)
            skill.stats.harm_history.append(skill.stats.harm_count)
            skill.last_updated = round_id
            self._save_skill(skill)

    def check_merge_needed(self, threshold: int) -> list[str]:
        """Return stages that have reached the merge threshold since last merge."""
        stages_needing_merge = []
        for stage, count in self._new_count_since_merge.items():
            if count >= threshold:
                stages_needing_merge.append(stage)
        return stages_needing_merge

    def reset_merge_counter(self, stage: str) -> None:
        self._new_count_since_merge[stage] = 0

    def remove_skill(self, name: str) -> None:
        skill = self._skills.pop(name, None)
        if skill:
            path = self._skill_path(skill)
            if path.exists():
                path.unlink()

    def merge_skills(
        self, names: list[str], merged_name: str, merged_summary: str,
        merged_keywords: list[str], merged_body: str, round_id: str = "round_1",
    ) -> Skill:
        """Merge multiple skills into one, inheriting summed stats."""
        total_match = sum(self._skills[n].stats.match_count for n in names if n in self._skills)
        total_help = sum(self._skills[n].stats.help_count for n in names if n in self._skills)
        total_harm = sum(self._skills[n].stats.harm_count for n in names if n in self._skills)
        stage = self._skills[names[0]].stage if names[0] in self._skills else "decomposer"

        for n in names:
            self.remove_skill(n)

        skill = Skill(
            name=re.sub(r"[^a-z0-9_]", "_", merged_name.lower().strip()),
            summary=merged_summary,
            keywords=[k.lower() for k in merged_keywords],
            stage=stage,
            body=merged_body,
            created_at=round_id,
            last_updated=round_id,
            stats=SkillStats(
                match_count=total_match,
                help_count=total_help,
                harm_count=total_harm,
            ),
        )
        self._skills[skill.name] = skill
        self._save_skill(skill)
        return skill

    def eliminate(self) -> list[str]:
        """Remove lowest-scoring skills when a stage exceeds its hard limit."""
        eliminated = []
        for stage, limit in self.limits.items():
            stage_skills = self.skills_by_stage(stage)
            if len(stage_skills) <= limit:
                continue

            never_matched = [s for s in stage_skills if s.stats.match_count == 0]
            for s in never_matched:
                self.remove_skill(s.name)
                eliminated.append(s.name)

            stage_skills = self.skills_by_stage(stage)
            if len(stage_skills) <= limit:
                continue

            sorted_skills = sorted(stage_skills, key=lambda s: s.stats.score)
            n_to_remove = len(stage_skills) - limit
            for s in sorted_skills[:n_to_remove]:
                self.remove_skill(s.name)
                eliminated.append(s.name)

        return eliminated

    def export_report(self) -> str:
        lines = ["Skill Library Report", "=" * 60]
        total = 0
        for stage in sorted(self.limits.keys()):
            skills = sorted(self.skills_by_stage(stage), key=lambda s: -s.stats.score)
            limit = self.limits[stage]
            lines.append(f"\n{stage.capitalize()} ({len(skills)}/{limit}):")
            for s in skills:
                flag = ""
                if s.stats.harm_ratio > 0.3:
                    flag = " ⚠️ harm>30%"
                elif s.stats.match_count == 0:
                    flag = " (unused)"
                lines.append(
                    f"  [{s.name}]  match:{s.stats.match_count}  "
                    f"help:{s.stats.help_count}  harm:{s.stats.harm_count}  "
                    f"eff:{s.stats.effectiveness:.2f}  score:{s.stats.score:.2f}{flag}"
                )
                total += 1
        total_limit = sum(self.limits.values())
        lines.append(f"\nTotal Skills: {total}/{total_limit}")
        return "\n".join(lines)
