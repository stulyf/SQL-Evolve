<p align="center">
  <h1 align="center">SQLaxy</h1>
  <p align="center">A Multi-Agent System for Text-to-SQL, powered by LangGraph</p>
</p>

<p align="center">
  <a href="./README_CN.md">中文</a> | English
</p>

---

## Introduction

SQLaxy is a multi-agent collaborative Text-to-SQL system built on [LangGraph](https://github.com/langchain-ai/langgraph). Given a natural language question and a database, SQLaxy automatically generates the corresponding SQL query through three specialized agents:

- **Selector** — Analyzes the database schema, prunes irrelevant tables and columns, and provides a focused schema to downstream agents.
- **Decomposer** — Decomposes complex questions into sub-questions and generates SQL step by step using chain-of-thought reasoning.
- **Refiner** — Executes the generated SQL against the database, detects errors, and iteratively refines the query until it passes validation.

The agent orchestration is implemented as a LangGraph `StateGraph`, with the Refiner using a conditional self-loop for automatic error correction.

```
┌──────────┐     ┌──────────────┐     ┌──────────┐
│ Selector │────▶│  Decomposer  │────▶│  Refiner  │──▶ Output
└──────────┘     └──────────────┘     └────┬──────┘
                                           │  ▲
                                           │  │ need_refine
                                           └──┘
```

SQLaxy currently supports evaluation on the [BIRD](https://bird-bench.github.io/) and [Spider](https://yale-lily.github.io/spider) benchmarks.

## Setup

### 1. Environment

```bash
conda create -n sqlaxy python=3.9 -y
conda activate sqlaxy
pip install -r requirements.txt
python -c "import nltk; nltk.download('punkt')"
```

### 2. Configuration

SQLaxy uses environment variables for LLM configuration. It is compatible with any OpenAI-compatible API (OpenAI, DeepSeek, local models, etc.):

```bash
export OPENAI_API_KEY="your-api-key"

# Optional: override model and endpoint (defaults shown below)
# export MODEL_NAME="deepseek-chat"
# export OPENAI_API_BASE="https://api.deepseek.com/v1"
```

### 3. Data Preparation

Download the BIRD and/or Spider datasets and place them under the `data/` directory:

```
data/
├── bird/
│   ├── dev.json
│   ├── dev_tables.json
│   └── dev_databases/
│       ├── california_schools/
│       │   └── california_schools.sqlite
│       └── ...
└── spider/
    ├── dev.json
    ├── tables.json
    └── database/
        ├── concert_singer/
        │   └── concert_singer.sqlite
        └── ...
```

The `data/` directory is excluded from version control via `.gitignore`.

## Usage

### Run on BIRD dev set

```bash
mkdir -p outputs/bird_dev

python run.py --dataset_name "bird" \
  --dataset_mode="dev" \
  --input_file "./data/bird/dev.json" \
  --db_path "./data/bird/dev_databases" \
  --tables_json_path "./data/bird/dev_tables.json" \
  --output_file "./outputs/bird_dev/output_bird.json" \
  --log_file "./outputs/bird_dev/log.txt"
```

### Run on Spider dev set

```bash
mkdir -p outputs/spider_dev

python run.py --dataset_name "spider" \
  --dataset_mode="dev" \
  --input_file "./data/spider/dev.json" \
  --db_path "./data/spider/database" \
  --tables_json_path "./data/spider/tables.json" \
  --output_file "./outputs/spider_dev/output_spider.json" \
  --log_file "./outputs/spider_dev/log.txt"
```

### Options

| Argument | Description |
|----------|-------------|
| `--dataset_name` | `bird` or `spider` |
| `--dataset_mode` | `dev`, `test`, or `train` |
| `--input_file` | Path to the dataset JSON file |
| `--db_path` | Path to the database directory |
| `--tables_json_path` | Path to the schema description file |
| `--output_file` | Path for output results (supports resume) |
| `--log_file` | Path for detailed logs |
| `--start_pos` | Resume from a specific position (default: 0) |
| `--without_selector` | Skip schema pruning |

The program supports **checkpoint resume** — if interrupted, re-run the same command and it will skip already completed items.

## Project Structure

```
SQLaxy/
├── core/
│   ├── state.py        # SQLaxyState (TypedDict) — shared state definition
│   ├── graph.py        # LangGraph StateGraph construction (build_graph)
│   ├── agents.py       # Selector, Decomposer, Refiner agent logic
│   ├── llm.py          # LLM API wrapper (langchain-openai ChatOpenAI)
│   ├── const.py        # Prompt templates and constants
│   └── utils.py        # Parsing and utility functions
├── evaluation/         # Evaluation scripts (EX, VES)
├── scripts/            # SQLite execution demo (Flask)
├── data/               # Datasets (excluded from git)
├── outputs/            # Run outputs (excluded from git)
├── run.py              # Main entry point
├── requirements.txt    # Python dependencies
└── LICENSE             # Apache 2.0
```

## Acknowledgements

SQLaxy is built upon and inspired by the following projects:

- **[MAC-SQL](https://github.com/wbbeyourself/MAC-SQL)** — The multi-agent collaborative Text-to-SQL framework (COLING 2025) that SQLaxy is forked from. We gratefully acknowledge the original authors for their foundational work on the Selector-Decomposer-Refiner architecture.

- **[LangGraph](https://github.com/langchain-ai/langgraph)** — The low-level orchestration framework for building stateful agents. SQLaxy uses LangGraph's `StateGraph` for agent workflow management, conditional routing, and state persistence.

## License

This project is licensed under the [Apache License 2.0](./LICENSE).
