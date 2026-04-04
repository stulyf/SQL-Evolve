# SQL-Evolve

**Distilling Skills from Errors — A Self-Evolving Multi-Agent Text-to-SQL System**

[Python 3.9+](https://www.python.org/downloads/)
[License: Apache 2.0](./LICENSE)
[LangGraph](https://github.com/langchain-ai/langgraph)

[English](./README.md) | [中文](./README_CN.md)

---

## What is SQL-Evolve?

SQL-Evolve is a multi-agent Text-to-SQL system that **learns from its own mistakes**. Beyond the standard Selector → Decomposer → Refiner pipeline, SQL-Evolve introduces an **error-driven skill evolution loop**: it automatically analyzes failed SQL queries, distills reusable strategies ("skills") from error patterns, and injects them back into the pipeline — making itself progressively better over iterations.

### Key Features

- **Three-Agent Pipeline** — Selector (schema pruning) → Decomposer (CoT SQL generation) → Refiner (execution-based error correction), orchestrated via LangGraph `StateGraph`
- **Self-Evolving Skill Discovery** — Automatically analyzes wrong answers, groups error patterns, and creates generalizable SQL writing strategies
- **Meta-Skill Operations** — Create / Merge / Split / Eliminate — the skill library manages its own lifecycle
- **Two-Layer Skill Loading** — Lightweight index (always loaded) + full skill body (loaded on demand), reducing context overhead by ~85%
- **Checkpoint Resume** — Interrupted? Just re-run. Already completed items are skipped automatically.
- **Model Agnostic** — Works with any OpenAI-compatible API (DeepSeek, GPT-4, local models, etc.)

---

## Results

### BIRD-dev (EX Accuracy)

All numbers are **execution accuracy (EX)** on the full BIRD `dev` split (**1534** questions), using the same evaluation protocol as the official BIRD leaderboard (predicted SQL executed against the gold database; result sets must match).


| Setting             | Role                                                                                                     | Output directory (this repo)    |
| ------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------- |
| **Baseline**        | Selector → Decomposer → Refiner, **no** injected skills                                                  | `outputs/bird_dev/`             |
| **+ Skills (ours)** | Same pipeline with **error-driven skills** loaded into prompts (after distillation from baseline errors) | `outputs/bird_dev_with_skills/` |


Both runs use `**deepseek-chat`** as the backbone LLM and the same data paths as in [Quick Start](#4-run). Metrics are aggregated from `eval_result_dev.json` in each output folder (`res == 1` counts as correct).


| Difficulty  | Baseline (correct / total) | Baseline   | + Skills (correct / total) | + Skills   | Δ (pp)    |
| ----------- | -------------------------- | ---------- | -------------------------- | ---------- | --------- |
| Simple      | 606 / 925                  | 65.51%     | 624 / 925                  | 67.46%     | **+1.95** |
| Moderate    | 237 / 465                  | 50.97%     | 244 / 465                  | 52.47%     | **+1.50** |
| Challenging | 71 / 144                   | 49.31%     | 72 / 144                   | 50.00%     | **+0.69** |
| **Overall** | **914 / 1534**             | **59.58%** | **940 / 1534**             | **61.28%** | **+1.70** |




---

## Architecture

![SQL-Evolve Architecture](./assets/SQL-Evolve.png)

---

## Quick Start

### 1. Install

```bash
conda create -n sql-evolve python=3.9 -y
conda activate sql-evolve
pip install -r requirements.txt
python -c "import nltk; nltk.download('punkt')"
```

### 2. Configure

```bash
export OPENAI_API_KEY="your-api-key"

# Optional: override model and endpoint (defaults shown below)
# export MODEL_NAME="deepseek-chat"
# export OPENAI_API_BASE="https://api.deepseek.com/v1"
```

### 3. Prepare Data

Download [BIRD](https://bird-bench.github.io/) and/or [Spider](https://yale-lily.github.io/spider) datasets:

```
data/
├── bird/
│   ├── dev.json
│   ├── dev_tables.json
│   └── dev_databases/
│       └── <db_id>/<db_id>.sqlite
└── spider/
    ├── dev.json
    ├── tables.json
    └── database/
        └── <db_id>/<db_id>.sqlite
```

### 4. Run

```bash
# BIRD dev set
mkdir -p outputs/bird_dev
python run.py --dataset_name bird \
  --dataset_mode dev \
  --input_file ./data/bird/dev.json \
  --db_path ./data/bird/dev_databases \
  --tables_json_path ./data/bird/dev_tables.json \
  --output_file ./outputs/bird_dev/output_bird.json \
  --log_file ./outputs/bird_dev/log.txt

# Spider dev set
mkdir -p outputs/spider_dev
python run.py --dataset_name spider \
  --dataset_mode dev \
  --input_file ./data/spider/dev.json \
  --db_path ./data/spider/database \
  --tables_json_path ./data/spider/tables.json \
  --output_file ./outputs/spider_dev/output_spider.json \
  --log_file ./outputs/spider_dev/log.txt
```

### 5. Evaluate

```bash
# BIRD EX + VES evaluation
bash evaluation_bird_ex_ves.sh
```

---

## Self-Evolving Skill Discovery

The core innovation of SQL-Evolve: **automatically distill reusable strategies from wrong answers**.

### How It Works

1. **Run baseline** — Execute the pipeline on a dataset, collect all wrong answers
2. **Analyze errors** — Classify each error (wrong JOIN, wrong aggregation, etc.) and locate which stage caused it
3. **Match skills** — Check if any existing skill already covers the error pattern
4. **Create skills** — For unmatched errors, group by pattern and call a reasoning model to propose generalizable strategies
5. **Merge & Eliminate** — Periodically merge overlapping skills; eliminate low-effectiveness ones when limits are reached
6. **Re-run with skills** — Inject skills into prompts and re-run to verify improvement

### Run the Evolve Loop

```bash
# Step 1: Analyze errors from existing results (no LLM calls)
python -m evosql.runner \
  --eval-result ./outputs/bird_dev/eval_result_dev.json \
  --output-jsonl ./outputs/bird_dev/output_bird.json \
  --skill-dir ./evosql/skills \
  --dry-run

# Step 2: Generate skills (calls reasoning model)
python -m evosql.runner \
  --eval-result ./outputs/bird_dev/eval_result_dev.json \
  --output-jsonl ./outputs/bird_dev/output_bird.json \
  --skill-dir ./evosql/skills \
  --merge-threshold 8
```

### Skill Example

Each skill is a Markdown file with YAML metadata, stored in `evosql/skills/<stage>/`:

```markdown
---
name: multi_table_join
summary: Verify foreign key path completeness for multi-table JOINs
keywords: [join, foreign key, multi-table, inner join]
stage: decomposer
stats:
  match_count: 47
  help_count: 31
  effectiveness: 0.66
---

## Rules

1. Before writing JOINs, trace the complete foreign key path between all required tables
2. Every JOIN must have an explicit ON condition — never use implicit comma-separated tables
3. Prefer INNER JOIN; use LEFT JOIN only when unmatched rows must be preserved

## Examples

❌ SELECT ... FROM A, B, C WHERE A.id = B.id
✅ SELECT ... FROM A JOIN B ON A.id = B.id JOIN C ON B.cid = C.id
```

---

## CLI Reference


| Argument             | Description                     | Default |
| -------------------- | ------------------------------- | ------- |
| `--dataset_name`     | `bird` or `spider`              | —       |
| `--dataset_mode`     | `dev`, `test`, or `train`       | `dev`   |
| `--input_file`       | Path to dataset JSON            | —       |
| `--db_path`          | Path to database directory      | —       |
| `--tables_json_path` | Path to schema description file | —       |
| `--output_file`      | Output path (supports resume)   | —       |
| `--log_file`         | Detailed log path               | —       |
| `--start_pos`        | Resume from position N          | `0`     |
| `--without_selector` | Skip schema pruning             | off     |
| `--use_gold_schema`  | Use gold schema (BIRD ablation) | off     |


---

## Project Structure

```
SQL-Evolve/
├── core/                  # Three-agent pipeline
│   ├── state.py           # SQLaxyState — shared state definition
│   ├── graph.py           # LangGraph StateGraph construction
│   ├── agents.py          # Selector, Decomposer, Refiner logic
│   ├── llm.py             # LLM API wrapper (OpenAI-compatible)
│   ├── const.py           # Prompt templates and constants
│   └── utils.py           # SQL parsing and utilities
├── evosql/                # Self-evolving skill discovery
│   ├── config.py          # Evolution parameters
│   ├── error_analyzer.py  # Error classification & root cause analysis
│   ├── skill_manager.py   # Skill CRUD, stats, merge, eliminate
│   ├── skill_matcher.py   # Zero-cost keyword matching
│   ├── proposer.py        # Reasoning model integration
│   ├── generator.py       # Skill file generation
│   ├── runner.py          # Evolution loop orchestration
│   ├── prompt_injector.py # Two-layer skill loading
│   └── skills/            # Skill library (per-stage)
│       ├── selector/
│       ├── decomposer/
│       └── refiner/
├── evaluation/            # BIRD (EX/VES) & Spider evaluation
├── scripts/               # Flask demo for SQL execution
├── run.py                 # Main entry point
├── requirements.txt
└── LICENSE                # Apache 2.0
```

---

## Acknowledgements

SQL-Evolve builds upon the following projects:

- **[MAC-SQL](https://github.com/wbbeyourself/MAC-SQL)** — The multi-agent collaborative Text-to-SQL framework (COLING 2025). SQL-Evolve extends the Selector-Decomposer-Refiner architecture with self-evolving skill discovery.
- **[LangGraph](https://github.com/langchain-ai/langgraph)** — The orchestration framework for building stateful agent workflows.
- **[EvoSkill](https://github.com/sentient-agi/EvoSkill)** — Inspiration for the evolutionary skill discovery paradigm.

---

## Citation

If you find SQL-Evolve useful, please consider giving it a star and citing:

```bibtex
@software{sql_evolve_2025,
  title  = {SQL-Evolve: Distilling Skills from Errors for Self-Evolving Text-to-SQL},
  author = {Yu-Feng Li},
  year   = {2026},
  url    = {https://github.com/stulyf/SQLaxy},
}
```

## License

This project is licensed under the [Apache License 2.0](./LICENSE).