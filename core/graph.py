# -*- coding: utf-8 -*-
from typing import Any, Optional

from langgraph.graph import END, StateGraph

from core.agents import Selector, decomposer_process, refiner_process
from core.const import MAX_ROUND
from core.llm import init_log_path, safe_call_llm
from core.state import SQLaxyState


def _load_skill_manager(skill_dir: Optional[str]):
    if not skill_dir:
        return None
    from evosql.skill_manager import SkillManager
    manager = SkillManager(skill_dir)
    skills = manager.all_skills()
    if skills:
        print(f"[Skills] Loaded {len(skills)} skills from {skill_dir}", flush=True)
    else:
        print(f"[Skills] No skills found in {skill_dir}", flush=True)
    return manager


def build_graph(
    data_path: str,
    tables_json_path: str,
    dataset_name: str,
    log_path: Optional[str],
    without_selector: bool = False,
    skill_dir: Optional[str] = None,
) -> Any:
    """
    Build compiled LangGraph: selector -> decomposer -> refiner (+ refiner self-loop when need_refine).
    When skill_dir is provided, skills are dynamically injected into each stage's prompt.
    """
    init_log_path(log_path or "")

    print("Checking network status...", flush=True)
    safe_call_llm("Hello world!")
    print("Network is available", flush=True)

    skill_manager = _load_skill_manager(skill_dir)

    selector = Selector(
        data_path=data_path,
        tables_json_path=tables_json_path,
        model_name="gpt-4",
        dataset_name=dataset_name,
        lazy=True,
        without_selector=without_selector,
    )

    def selector_node(state: SQLaxyState):
        return selector.process(state)

    def decomposer_node(state: SQLaxyState):
        return decomposer_process(state, dataset_name, skill_manager=skill_manager)

    def refiner_node(state: SQLaxyState):
        return refiner_process(state, data_path, dataset_name, skill_manager=skill_manager)

    def route_after_refiner(state: SQLaxyState):
        if state.get("need_refine") and state.get("try_times", 0) < MAX_ROUND:
            return "again"
        return "done"

    workflow = StateGraph(SQLaxyState)
    workflow.add_node("selector", selector_node)
    workflow.add_node("decomposer", decomposer_node)
    workflow.add_node("refiner", refiner_node)
    workflow.set_entry_point("selector")
    workflow.add_edge("selector", "decomposer")
    workflow.add_edge("decomposer", "refiner")
    workflow.add_conditional_edges(
        "refiner",
        route_after_refiner,
        {"again": "refiner", "done": END},
    )
    return workflow.compile()
