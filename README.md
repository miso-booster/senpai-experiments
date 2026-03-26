Automated Prompt Interface
==========================

Run a shared prompt set against multiple architectures, store the raw results in
`out/`, and generate the analysis artifacts used for RQ1, RQ2, and RQ3.

This README is organized around the actual execution flow:

1. Install dependencies
2. Configure architectures, prompts, and environment variables
3. Run executions
4. Run the analysis pipelines you need

Quick Start
-----------

Requirements

- Python 3.12+
- `uv` recommended, or `pip`

Install dependencies with `uv`:

```bash
uv sync
```

Or with `pip`:

```bash
python -m pip install -r requirements.txt
```

Configuration
-------------

### 1. Architectures

Edit `configs/architectures.json`.

For each architecture, make sure:

- `cmd` points to the correct Python executable
- `cwd` points to the root of the target project
- `env_file` points to the `.env` file to load

### 2. Prompt sets

The main runner selects prompts from one of these files:

- `configs/prompts.json` for `-rq2`
- `configs/rq3_prompts.json` for `-rq3`
- `configs/rq4_prompts.json` for `-rq4`

### 3. Environment variables

Create `configs/.env` if you use the default env path:

```ini
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=your_project_name
LANGSMITH_TRACING=true
OPENAI_API_KEY=your_openai_key
```

`OPENAI_API_KEY` is required for `app.rq3_clustering`.

Main Execution
--------------

The main runner is:

```bash
python -m app.main
```

You must choose exactly one prompt set:

- `-rq2`
- `-rq3`
- `-rq4`

Examples:

```bash
python -m app.main -rq2
python -m app.main -rq3
python -m app.main -rq4
python -m app.main -rq2 -r 20
python -m app.main -rq2 -r 20 -v
```

Important flags:

- `-r, --runs`: number of repeated executions
- `-v, --verbose`: verbose logging

Execution Outputs
-----------------

Every run writes:

- `out/results.jsonl`: append-only raw run log
- `out/runs/<run_group_id>/results.xlsx`: one workbook for that execution batch

`<run_group_id>` is timestamp-based, so each execution batch gets its own folder.

The generated results also include `is_yaml_valid` for prompt types that expect YAML.

Analysis Workflows
------------------

RQ1: Ranking Sheets
-------------------

Generate the randomized ranking package:

```bash
python -m app.rq1.generate_rankings
```

This reads the first run folder under `out/runs/architecture_comparison/` by
default. You can override that with `--run-id`.

Main outputs in `out/RQ1/<run_id>/`:

- `ranking.md`
- `key.csv`
- `answers.csv`

Aggregate completed subject answers:

```bash
python -m app.rq1.aggregate_rankings
```

Useful flags:

- `--run-id <run_id>`
- `--answers-dir <path>`

Main aggregate outputs:

- `metrics_overall.csv`
- `metrics_per_prompt.csv`
- `metrics_pairwise.csv`

RQ2: Architecture Metrics Aggregation
-------------------------------------

Aggregate metrics across execution runs:

```bash
python -m app.rq2
```

This produces the main RQ2 workbook and plots from the execution results.

The RQ2 workbook includes:

- aggregated per-architecture metrics
- pairwise Wilcoxon signed-rank tests on matched `run_group_id + prompt_id` rows

Supplementary fallback/answer join:

```bash
python app/rq2/fallback_answer_join.py
```

This writes:

- `out/RQ2_architecture_metrics/rq2_fallback_answers_joined.xlsx`

Useful flags for the join script:

- `--runs-dir`
- `--out-dir`
- `--sheet`
- `--architectures`
- `--include-no-fallbacks`

RQ3: Tool and Node Consistency
------------------------------

Run the RQ3 consistency pipeline:

```bash
python -m app.rq3_consistency
```

Default input:

- `out/runs/advanced_prompt_arch_comparison/`

Default output directory:

- `out/RQ3_tool_consistency_and_node_usage_consistency/`

This workflow reads repeated LangSmith tracing exports (`tracing_*.xlsx`) and
measures whether the architectures behave consistently from run to run.

It computes:

- tool-use consistency across repeated runs of the same prompt
- graph-node usage consistency for the graph-based architecture

This is the tracing-based RQ3 analysis. It is separate from `app.rq3_clustering`,
which clusters final answers instead of comparing tool or node traces.

Main outputs:

- `RQ3_tool_consistency_and_node_usage_consistency.xlsx`
- tool consistency plots
- node usage consistency plots

RQ3: Answer Clustering
----------------------

This is a separate RQ3 workflow. It clusters repeated answers per
architecture/prompt and supports a human review pass before computing final
metrics.

### Phase 1: Generate clustering proposals

```bash
python -m app.rq3_clustering
```

Default input:

- `out/runs/advanced_prompt_arch_comparison/`

Default output directory:

- `out/RQ3_clustering/`

Main outputs:

- one workbook per architecture, such as `agentic_architecture_answer_clustering.xlsx`
- `RQ3_clustering_manifest.xlsx`
- `RQ3_clustering_review_template.xlsx`
- optional cache files under `out/RQ3_clustering/_cluster_cache/`

Useful flags:

- `--model <name>`
- `--force-refresh`
- `--max-groups N`
- `--prepare-only`

### Phase 2: Human review and final metrics

Edit:

- `out/RQ3_clustering/RQ3_clustering_review_template.xlsx`

Work mainly in the `review_assignments` sheet. The important columns are:

- `proposed_cluster_id`
- `proposed_cluster_label`
- `proposed_cluster_reason`
- `final_cluster_id`
- `reviewed`
- `review_notes`

Recommended review flow:

- if the proposed cluster is correct, keep `final_cluster_id` and set `reviewed=TRUE`
- if it is wrong, change `final_cluster_id` to another cluster id such as `C2` or a new one such as `C4`, then set `reviewed=TRUE`
- use `review_cluster_reference` as the lookup sheet

Compute final reviewed metrics:

```bash
python -m app.rq3_clustering.review_metrics
```

If the review is still incomplete:

```bash
python -m app.rq3_clustering.review_metrics --allow-pending
```

Main outputs:

- `out/RQ3_clustering/RQ3_clustering_reviewed_metrics.xlsx`
- one reviewed workbook per architecture
- reviewed overall plots
- reviewed prompt-level plots

Useful flags:

- `--allow-pending`
- `--export-csvs`
- `--no-plots`
- `--plot-format <png|pdf|svg>`
- `--dpi <int>`
