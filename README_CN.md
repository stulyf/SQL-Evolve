

# SQL-Evolve

**从错误中蒸馏技能 —— 自进化的多智能体 Text-to-SQL 系统**

[Python 3.9+](https://www.python.org/downloads/)
[License: Apache 2.0](./LICENSE)
[LangGraph](https://github.com/langchain-ai/langgraph)

[English](./README.md) | [中文](./README_CN.md)



---

## 什么是 SQL-Evolve？

SQL-Evolve 是一个能**从自身错误中学习**的多智能体 Text-to-SQL 系统。在标准的 Selector → Decomposer → Refiner 流水线之上，SQL-Evolve 引入了**错题驱动的技能进化循环**：自动分析失败的 SQL 查询，从错误模式中蒸馏出可复用的策略（"技能"），并将其注入回流水线——让系统在迭代中逐步变强。

### 核心特性

- **三智能体流水线** — Selector（schema 裁剪）→ Decomposer（CoT SQL 生成）→ Refiner（执行修复），由 LangGraph `StateGraph` 编排
- **自进化技能发现** — 自动分析错题，按错误模式分组，生成可泛化的 SQL 编写策略
- **元技能操作** — 创建 / 合并 / 拆分 / 淘汰，技能库自我管理生命周期
- **两层技能加载** — 轻量索引（始终加载）+ 全文内容（按需加载），上下文开销降低 ~85%
- **断点续跑** — 中断后重新执行相同命令，自动跳过已完成的条目
- **模型无关** — 兼容任何 OpenAI 兼容接口（DeepSeek、GPT-4、本地模型等）

---

## 性能

### BIRD-dev（EX 准确率）


| 难度          | 正确 / 总数        | 准确率       |
| ----------- | -------------- | --------- |
| Simple      | 606 / 925      | 65.5%     |
| Moderate    | 237 / 465      | 51.0%     |
| Challenging | 71 / 144       | 49.3%     |
| **总计**      | **914 / 1534** | **59.6%** |


> 使用 `deepseek-chat` 作为骨干 LLM 评测。

---

## 架构

<p align="center">
  <img src="./assets/SQL-Evolve.png" alt="SQL-Evolve 架构图" width="90%">
</p>


---

## 快速开始

### 1. 安装

```bash
conda create -n sql-evolve python=3.9 -y
conda activate sql-evolve
pip install -r requirements.txt
python -c "import nltk; nltk.download('punkt')"
```

### 2. 配置 LLM

```bash
export OPENAI_API_KEY="你的API密钥"

# 可选：覆盖模型名和端点（以下为默认值）
# export MODEL_NAME="deepseek-chat"
# export OPENAI_API_BASE="https://api.deepseek.com/v1"
```

### 3. 准备数据

下载 [BIRD](https://bird-bench.github.io/) 和/或 [Spider](https://yale-lily.github.io/spider) 数据集：

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

### 4. 运行

```bash
# BIRD dev 集
mkdir -p outputs/bird_dev
python run.py --dataset_name bird \
  --dataset_mode dev \
  --input_file ./data/bird/dev.json \
  --db_path ./data/bird/dev_databases \
  --tables_json_path ./data/bird/dev_tables.json \
  --output_file ./outputs/bird_dev/output_bird.json \
  --log_file ./outputs/bird_dev/log.txt

# Spider dev 集
mkdir -p outputs/spider_dev
python run.py --dataset_name spider \
  --dataset_mode dev \
  --input_file ./data/spider/dev.json \
  --db_path ./data/spider/database \
  --tables_json_path ./data/spider/tables.json \
  --output_file ./outputs/spider_dev/output_spider.json \
  --log_file ./outputs/spider_dev/log.txt
```

### 5. 评测

```bash
# BIRD EX + VES 评测
bash evaluation_bird_ex_ves.sh
```

---

## 自进化技能发现

SQL-Evolve 的核心创新：**从错题中自动蒸馏出可复用的 SQL 编写策略**。

### 工作流程

1. **跑基线** — 在数据集上执行流水线，收集所有错题
2. **错误分析** — 分类每个错误（错误 JOIN、错误聚合等），定位是哪个阶段导致的
3. **匹配技能** — 检查现有技能库中是否有 skill 覆盖该错误模式
4. **创建技能** — 对未匹配的错误按模式分组，调用推理模型提出可泛化的策略
5. **合并与淘汰** — 定期合并重叠的 skill；超出上限时淘汰低效 skill
6. **带技能重跑** — 将 skill 注入 prompt 后重新运行，验证效果提升

### 运行进化循环

```bash
# 第一步：分析现有结果中的错误（不调用 LLM）
python -m evosql.runner \
  --eval-result ./outputs/bird_dev/eval_result_dev.json \
  --output-jsonl ./outputs/bird_dev/output_bird.json \
  --skill-dir ./evosql/skills \
  --dry-run

# 第二步：生成技能（调用推理模型）
python -m evosql.runner \
  --eval-result ./outputs/bird_dev/eval_result_dev.json \
  --output-jsonl ./outputs/bird_dev/output_bird.json \
  --skill-dir ./evosql/skills \
  --merge-threshold 8
```

### 技能示例

每个技能是一个带 YAML 元数据的 Markdown 文件，存储在 `evosql/skills/<阶段>/` 下：

```markdown
---
name: multi_table_join
summary: 多表 JOIN 时验证外键路径完整性
keywords: [join, 外键, 多表, inner join]
stage: decomposer
stats:
  match_count: 47
  help_count: 31
  effectiveness: 0.66
---

## 规则

1. 写 JOIN 前，先沿外键路径确认所有必需的表都已包含
2. 每个 JOIN 必须有明确的 ON 条件 — 禁止使用逗号分隔的隐式 JOIN
3. 优先使用 INNER JOIN；仅在需要保留无匹配行时使用 LEFT JOIN

## 示例

❌ SELECT ... FROM A, B, C WHERE A.id = B.id
✅ SELECT ... FROM A JOIN B ON A.id = B.id JOIN C ON B.cid = C.id
```

---

## 命令行参数


| 参数                   | 说明                      | 默认值   |
| -------------------- | ----------------------- | ----- |
| `--dataset_name`     | `bird` 或 `spider`       | —     |
| `--dataset_mode`     | `dev`、`test` 或 `train`  | `dev` |
| `--input_file`       | 数据集 JSON 路径             | —     |
| `--db_path`          | 数据库目录路径                 | —     |
| `--tables_json_path` | schema 描述文件路径           | —     |
| `--output_file`      | 输出路径（支持断点续跑）            | —     |
| `--log_file`         | 详细日志路径                  | —     |
| `--start_pos`        | 从第 N 条开始                | `0`   |
| `--without_selector` | 跳过 schema 裁剪            | 关闭    |
| `--use_gold_schema`  | 使用 gold schema（BIRD 消融） | 关闭    |


---

## 项目结构

```
SQL-Evolve/
├── core/                  # 三智能体流水线
│   ├── state.py           # SQLaxyState — 共享状态定义
│   ├── graph.py           # LangGraph StateGraph 构建
│   ├── agents.py          # Selector、Decomposer、Refiner 逻辑
│   ├── llm.py             # LLM API 封装（OpenAI 兼容）
│   ├── const.py           # Prompt 模板与常量
│   └── utils.py           # SQL 解析与工具函数
├── evosql/                # 自进化技能发现
│   ├── config.py          # 进化参数配置
│   ├── error_analyzer.py  # 错误分类与根因分析
│   ├── skill_manager.py   # Skill CRUD、统计、合并、淘汰
│   ├── skill_matcher.py   # 零成本关键词匹配
│   ├── proposer.py        # 推理模型集成
│   ├── generator.py       # Skill 文件生成
│   ├── runner.py          # 进化循环编排
│   ├── prompt_injector.py # 两层技能加载
│   └── skills/            # 技能库（按阶段分层）
│       ├── selector/
│       ├── decomposer/
│       └── refiner/
├── evaluation/            # BIRD (EX/VES) 与 Spider 评测
├── scripts/               # Flask SQL 执行演示
├── run.py                 # 主入口
├── requirements.txt
└── LICENSE                # Apache 2.0
```

---

## 致谢

SQL-Evolve 基于以下项目构建：

- **[MAC-SQL](https://github.com/wbbeyourself/MAC-SQL)** — 多智能体协作 Text-to-SQL 框架（COLING 2025）。SQL-Evolve 在其 Selector-Decomposer-Refiner 架构基础上扩展了自进化技能发现。
- **[LangGraph](https://github.com/langchain-ai/langgraph)** — 构建有状态智能体工作流的编排框架。
- **[EvoSkill](https://github.com/sentient-agi/EvoSkill)** — 进化式技能发现范式的灵感来源。

---

## 引用

如果 SQL-Evolve 对你有帮助，请考虑给个 Star 并引用：

```bibtex
@software{sql_evolve_2025,
  title  = {SQL-Evolve: Distilling Skills from Errors for Self-Evolving Text-to-SQL},
  author = {Yu-Feng Li},
  year   = {2026},
  url    = {https://github.com/stulyf/SQLaxy},
}
```

## 许可证

本项目基于 [Apache License 2.0](./LICENSE) 开源。