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
python -m app.main -rq2
```

Optional verbose logging:

```powershell
python -m app.main -rq2 -v
```

Configuration
-------------
1) Architectures and paths  
Edit `configs/architectures.json` and ensure:
- `cmd` points to the correct Python executable for each architecture.
- `cwd` points to the root of each Sensei project.
- `env_file` points to your `.env` file (default is `configs/.env`).

2) Prompts  
Edit `configs/prompts.json`, `configs/rq3_prompts.json`, or `configs/rq4_prompts.json`
to add or change prompts for the corresponding execution mode.

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

Generate the joined fallback/answer spreadsheet with:

```powershell
python app/rq2/fallback_answer_join.py
```

This reads all `results.xlsx` files under `out/runs/architecture_comparison`, filters
and pivots answers/fallback flags by `run_group_id + prompt_id`, keeps prompts
where at least one architecture fell back, and writes
`out/RQ2_architecture_metrics/rq2_fallback_answers_joined.xlsx`.
Change `--runs-dir`, `--out-dir`, `--sheet`, `--architectures`, or add
`--include-no-fallbacks` for other inputs/filters.

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
RQ3 Clustering loads repeated `results.xlsx` files, splits the answers by
architecture and prompt, and uses the OpenAI API to semantically cluster the
repeated answers for each prompt. This is intended for runs such as 20 repeated
executions of 15 prompts across the three architectures, where the goal is to
measure response consistency.

Phase 1: LLM clustering proposal

```powershell
python -m app.rq3_clustering
```

By default this reads from `out/runs/advanced_prompt_arch_comparison/` and
writes the clustering workbooks to `out/RQ3_clustering/`.

Requirements
- `OPENAI_API_KEY` must be set.
- The default model is `gpt-4o-mini`.

Main outputs
- One workbook per architecture, for example `out/RQ3_clustering/agentic_architecture_answer_clustering.xlsx`
- Combined manifest workbook: `out/RQ3_clustering/RQ3_clustering_manifest.xlsx`
- Human review workbook: `out/RQ3_clustering/RQ3_clustering_review_template.xlsx`
- Optional cache files under `out/RQ3_clustering/_cluster_cache/`

Each architecture workbook includes:
- `answers_matrix`: prompt x run matrix of raw answers.
- `prompt_summary`: one row per prompt with the number of clusters and the majority-cluster share.
- `cluster_summary`: one row per discovered cluster with counts, shares, labels, and representative answers.
- `cluster_assignments`: one row per answer showing which cluster it belongs to.
- `review_assignments`: editable rows for human review of the LLM clustering using cluster IDs.
- `inventory`: raw answer inventory with source workbook information.

Useful flags
- `--model <name>` to override the clustering model.
- `--force-refresh` to ignore cached OpenAI cluster results.
- `--max-groups N` to cluster only the first `N` architecture/prompt groups.
- `--prepare-only` to skip the API call and export only the raw matrices/inventory.

Phase 2: Human-reviewed final metrics

Edit `out/RQ3_clustering/RQ3_clustering_review_template.xlsx`, specifically the
`review_assignments` sheet. The reviewer works mainly with:
- `proposed_cluster_id`
- `proposed_cluster_label`
- `proposed_cluster_reason`
- `final_cluster_id`
- `reviewed`
- `review_notes`

Recommended review flow:
- If the proposed cluster is correct, leave `final_cluster_id` unchanged and set `reviewed=TRUE`.
- If it is wrong, change `final_cluster_id` to another cluster id such as `C2`, or create a new one such as `C4`, and then set `reviewed=TRUE`.
- Use `review_cluster_reference` as the lookup sheet for cluster labels, reasons, counts, and response indexes.

Then compute the final metrics from the reviewed assignments:

```powershell
python -m app.rq3_clustering.review_metrics
```

By default, phase 2 requires all rows to have `reviewed=TRUE`. For interim
checks before review is finished, use:

```powershell
python -m app.rq3_clustering.review_metrics --allow-pending
```

This writes:
- `out/RQ3_clustering/RQ3_clustering_reviewed_metrics.xlsx`
- One reviewed workbook per architecture, for example `out/RQ3_clustering/agentic_architecture_answer_clustering_reviewed.xlsx`
- `out/RQ3_clustering/RQ3_clustering_reviewed_overall_summary.png`
- `out/RQ3_clustering/RQ3_clustering_reviewed_prompt_majority_share.png`
- `out/RQ3_clustering/RQ3_clustering_reviewed_prompt_cluster_count.png`
- `out/RQ3_clustering/RQ3_clustering_reviewed_majority_share_heatmap.png`
- `out/RQ3_clustering/RQ3_clustering_reviewed_difficulty_summary.png`

Useful phase-2 flags
- `--export-csvs` to also export the reviewed summaries as CSV files.
- `--allow-pending` to compute interim metrics before every row is marked as reviewed.
- `--no-plots` to skip figure generation and write only the reviewed workbooks/CSVs.
- `--plot-format <png|pdf|svg>` to change the reviewed plot format.

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
