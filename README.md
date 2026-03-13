Automated Prompt Interface
==========================

Small runner that loads architectures and prompts from `configs/` and executes
each prompt against each architecture, saving results to `out/`.

Requirements
------------
- Python 3.12+
- `uv` (recommended) or `pip`

Install dependencies
--------------------
Recommended:

```powershell
uv sync
```

If you do not use `uv`, install from `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

Run
---
```powershell
python -m app.main
```

Optional verbose logging:

```powershell
python -m app.main -v
```

Configuration
-------------
1) Architectures and paths  
Edit `configs/architectures.json` and ensure:
- `cmd` points to the correct Python executable for each architecture.
- `cwd` points to the root of each Sensei project.
- `env_file` points to your `.env` file (default is `configs/.env`).

2) Prompts  
Edit `configs/prompts.json` to add or change prompts.

3) Environment variables (`configs/.env`)  
Create `configs/.env` with the following keys:

```ini
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=your_project_name
LANGSMITH_TRACING=true
OPENAI_API_KEY=your_openai_key
```

Outputs
-------
- Per-run JSONL results: `out/results.jsonl`
- Per-group Excel: `out/runs/<run_group_id>/results.xlsx`

Research Questions
------------------

RQ1 (offline ranking sheets)
----------------------------
Generate a randomized ranking markdown + key + answers template:

```powershell
python -m app.rq1.generate_rankings
```

By default this uses the first run folder under `out/runs/architecture_comparison/`.
You can select a specific run with `--run-id <run_id>`.

This writes to `out/RQ1/<run_id>/` (CSV delimiter is `;`):
- `ranking.md` (responses randomized per prompt)
- `key.csv` (label -> arch/run mapping)
- `answers.csv` (template to fill in ranks)

Each response in `ranking.md` now includes `YAML: true|false|n/a` based on
`is_yaml_valid` from `results.xlsx`.

Aggregate multiple subjects (expects `answers_*.csv` and `key.csv`):

```powershell
python -m app.rq1.aggregate_rankings
```

By default this reads `out/RQ1/<run_id>/` for the
first run folder. You can select a specific run with `--run-id <run_id>` or pass
`--answers-dir` directly.

This also writes metrics CSVs in the same folder:
- `metrics_overall.csv` (per-architecture avg rank, Borda, win rate)
- `metrics_per_prompt.csv` (per-prompt avg rank + win rate)
- `metrics_pairwise.csv` (pairwise win rates)

RQ2 (architecture metrics aggregation)
-------------------------------------
RQ2 aggregates metrics across multiple execution runs and generates a workbook
plus comparison plots (averages and variability). The workbook now also includes
pairwise Wilcoxon signed-rank tests between architectures on matched
`run_group_id + prompt_id` rows.

```powershell
python -m app.rq2
```

RQ3 Consistency (tool and node-usage consistency across repeated runs)
----------------------------------------------------------------------
RQ3 measures:
- tool-use consistency across repeated runs of the same prompt from LangSmith
  tracing exports (`tracing_*.xlsx`, using `run_type == "tool"`), and
- node-usage consistency for the graph-based architecture using
  `metadata.langgraph_node` from top-level graph node executions.

Run:

```powershell
python -m app.rq3_consistency
```

By default this reads from `out/runs/advanced_prompt_arch_comparison/` and
generates the RQ3 workbook and plots in
`out/RQ3_tool_consistency_and_node_usage_consistency/`.

Legacy alias:

```powershell
python -m app.rq3
```

Outputs
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_and_node_usage_consistency.xlsx`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_similarity_and_toolcount.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_presence_heatmap.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_variability_summary.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_variability_mean_std.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_node_usage_consistency.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_node_usage_consistency_similarity_and_nodecount.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_node_usage_consistency_presence_heatmap.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_node_usage_consistency_variability_summary.png`
- `out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_node_usage_consistency_variability_mean_std.png`

RQ3 Clustering
--------------
RQ3 Clustering builds one answer matrix per architecture from repeated
`results.xlsx` files so the answers can be clustered or compared downstream.

Run:

```powershell
python -m app.rq3_clustering
```

By default this reads from `out/runs/advanced_prompt_arch_comparison/` and
writes the clustering workbooks to `out/RQ3_clustering/`.

Output structure per execution
------------------------------
Each execution writes to:

- `out/results.jsonl` (append-only): one JSON line per architecture/prompt run.
- `out/runs/<run_group_id>/results.xlsx`: a snapshot for that execution only.

`<run_group_id>` is a timestamp with milliseconds, so each execution gets its own
folder under `out/runs/`.

`results.jsonl` / `results.xlsx` include `is_yaml_valid`:
- `true` when YAML is valid for `profile`, `rule`, or `connector` prompts.
- `false` when YAML is found but invalid for those prompt types.
- `null` in `results.jsonl` (`None` in Python) and empty in `results.xlsx` when no YAML is found, or for non-YAML prompt types (for example `documentation`).

`results.jsonl` / `results.xlsx` also include `answer_code_lines`:
- Number of lines found inside Markdown fenced code blocks (triple backticks) in the assistant answer.
- Fence marker lines themselves are not counted.

`results.jsonl` / `results.csv` also include `answer_word_count`:
- Number of words in the assistant answer (split by whitespace).

Individual run folders
----------------------
Inside each run group, every architecture/prompt pair gets its own folder:

`out/runs/<run_group_id>/<run_id>/`

Files in each run folder:
- `answer.txt`: extracted assistant answer (from `$$$ ... $$$` blocks if present; otherwise full stdout).
- `cmd.json`: the exact command executed (array of args).
- `stdin.txt`: the prompt sent to the process plus the exit command.
- `stdout.txt`: raw stdout captured from the process.
- `stderr.txt`: raw stderr captured from the process.
