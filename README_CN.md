<p align="center">
  <h1 align="center">SQLaxy</h1>
  <p align="center">基于 LangGraph 的多智能体 Text-to-SQL 系统</p>
</p>

<p align="center">
  中文 | <a href="./README.md">English</a>
</p>

---

## 简介

SQLaxy 是一个基于 [LangGraph](https://github.com/langchain-ai/langgraph) 构建的多智能体协作 Text-to-SQL 系统。给定自然语言问题和数据库，SQLaxy 通过三个专用智能体自动生成对应的 SQL 查询：

- **Selector（选择器）** — 分析数据库 schema，裁剪无关的表和列，为下游智能体提供精简的 schema。
- **Decomposer（分解器）** — 将复杂问题分解为子问题，通过链式推理（Chain-of-Thought）逐步生成 SQL。
- **Refiner（优化器）** — 在数据库上执行生成的 SQL，检测错误并迭代修复，直到通过验证。

智能体编排采用 LangGraph 的 `StateGraph` 实现，Refiner 使用条件自循环边实现自动纠错。

```
┌──────────┐     ┌──────────────┐     ┌──────────┐
│ Selector │────▶│  Decomposer  │────▶│  Refiner  │──▶ 输出
└──────────┘     └──────────────┘     └────┬──────┘
                                           │  ▲
                                           │  │ need_refine
                                           └──┘
```

SQLaxy 目前支持在 [BIRD](https://bird-bench.github.io/) 和 [Spider](https://yale-lily.github.io/spider) 基准上进行评测。

## 环境配置

### 1. 创建环境

```bash
conda create -n sqlaxy python=3.9 -y
conda activate sqlaxy
pip install -r requirements.txt
python -c "import nltk; nltk.download('punkt')"
```

### 2. 配置 LLM

SQLaxy 通过环境变量配置 LLM，兼容任何 OpenAI 兼容接口（OpenAI、DeepSeek、本地模型等）：

```bash
export OPENAI_API_KEY="你的API密钥"

# 可选：覆盖模型名和端点（以下为默认值）
# export MODEL_NAME="deepseek-chat"
# export OPENAI_API_BASE="https://api.deepseek.com/v1"
```

### 3. 准备数据

下载 BIRD 和/或 Spider 数据集，放置到 `data/` 目录下：

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

`data/` 目录已通过 `.gitignore` 排除，不会提交到版本控制。

## 使用方法

### 在 BIRD dev 集上运行

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

### 在 Spider dev 集上运行

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

### 参数说明

| 参数 | 说明 |
|------|------|
| `--dataset_name` | `bird` 或 `spider` |
| `--dataset_mode` | `dev`、`test` 或 `train` |
| `--input_file` | 数据集 JSON 文件路径 |
| `--db_path` | 数据库目录路径 |
| `--tables_json_path` | schema 描述文件路径 |
| `--output_file` | 输出结果路径（支持断点续跑） |
| `--log_file` | 详细日志路径 |
| `--start_pos` | 从指定位置开始（默认：0） |
| `--without_selector` | 跳过 schema 裁剪 |

程序支持**断点续跑** — 如果中断，重新执行相同命令即可自动跳过已完成的条目。

## 项目结构

```
SQLaxy/
├── core/
│   ├── state.py        # SQLaxyState (TypedDict) — 共享状态定义
│   ├── graph.py        # LangGraph StateGraph 构建 (build_graph)
│   ├── agents.py       # Selector、Decomposer、Refiner 智能体逻辑
│   ├── llm.py          # LLM API 封装 (langchain-openai ChatOpenAI)
│   ├── const.py        # Prompt 模板与常量
│   └── utils.py        # 解析与工具函数
├── evaluation/         # 评测脚本 (EX, VES)
├── scripts/            # SQLite 执行演示 (Flask)
├── data/               # 数据集（不纳入 git）
├── outputs/            # 运行输出（不纳入 git）
├── run.py              # 主入口
├── requirements.txt    # Python 依赖
└── LICENSE             # Apache 2.0
```

## 致谢

SQLaxy 基于以下项目构建，在此表示感谢：

- **[MAC-SQL](https://github.com/wbbeyourself/MAC-SQL)** — 多智能体协作 Text-to-SQL 框架（COLING 2025），SQLaxy 由此 fork 而来。感谢原作者在 Selector-Decomposer-Refiner 架构上的开创性工作。

- **[LangGraph](https://github.com/langchain-ai/langgraph)** — 构建有状态智能体的底层编排框架。SQLaxy 使用 LangGraph 的 `StateGraph` 进行智能体工作流管理、条件路由和状态持久化。

## 许可证

本项目基于 [Apache License 2.0](./LICENSE) 开源。
