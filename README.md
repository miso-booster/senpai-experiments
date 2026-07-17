Automated Prompt Interface
==========================

This repository contains the experiment data and analysis artifacts for comparing different assistant architectures. It also includes the Python workflows needed to reproduce or extend the experiments.

Experiment Results
------------------

The complete, versioned results are in [`out/`](out/). The summaries below are an entry point; follow the links to inspect the underlying CSV, workbook, figure, and raw-run artifacts. Results are grouped by research question (RQ) and, where applicable, by model.

### At a glance

| Research question | What is available | Primary artifacts |
| --- | --- | --- |
| RQ1 | Human ranking of three architectures using `gpt-4o-mini` | [rankings and metrics](out/RQ1/gpt-4o-mini/20260324_134818_560/) |
| RQ2 | Architecture metrics for `gemini-3-1-pro-preview`, `gpt-4-1-mini`, `gpt-4o-mini`, and `gpt-5-codex` | [per-model reports](out/RQ2_architecture_metrics/) and [model comparison](out/RQ2_architecture_metrics/model_comparison/) |
| RQ3 | Trace consistency and human-reviewed answer clustering | [tool/node consistency](out/RQ3_tool_consistency_and_node_usage_consistency/) and [clustering results](out/RQ3_clustering/) |
| RQ4 | Guardrail-test metrics for four models and three architectures | [combined report](out/RQ4_guardrail_metrics/) and [judge-corrected results](out/RQ4_guardrail_metrics_judged/) |

### RQ1 - Result quality

The paper assesses syntactic quality through fallback and YAML-validity rates, and semantic quality through human rankings. The data remain available in [the RQ1 result directory](out/RQ1/gpt-4o-mini/20260324_134818_560/), including the [average-rank metrics](out/RQ1/gpt-4o-mini/20260324_134818_560/metrics_avg_prompt_rank.csv), [pairwise results](out/RQ1/gpt-4o-mini/20260324_134818_560/metrics_pairwise.csv), and [Friedman test](out/RQ1/gpt-4o-mini/20260324_134818_560/metrics_friedman.csv).

**Syntactic quality by model and architecture**

<p align="center">
  <img src="out/RQ2_architecture_metrics/model_comparison/RQ2_quality_fallback_rate.png" alt="Fallback rate by model and architecture" width="48%">
  <img src="out/RQ2_architecture_metrics/model_comparison/RQ2_quality_yaml_valid_rate.png" alt="YAML-valid rate by model and architecture" width="48%">
</p>

**Semantic quality - human ranking**

<p align="center">
  <img src="out/RQ1/gpt-4o-mini/20260324_134818_560/RQ1_weighted_avg_prompt_rank.png" alt="Confidence-weighted average rank" width="32%">
  <img src="out/RQ1/gpt-4o-mini/20260324_134818_560/RQ1_pairwise_summary.png" alt="Prompt-level pairwise wins" width="32%">
  <img src="out/RQ1/gpt-4o-mini/20260324_134818_560/RQ1_position_distribution.png" alt="Distribution of ranking positions" width="32%">
</p>

### RQ2 - Cost

RQ2 reports response time, input-token consumption, LLM calls, and answer size per response. The model-level workbooks and data are available under [RQ2 architecture metrics](out/RQ2_architecture_metrics/), with a [cross-model comparison](out/RQ2_architecture_metrics/model_comparison/).

<p align="center">
  <img src="out/RQ2_architecture_metrics/gpt-4o-mini/RQ2_per_response_distribution_latency_s.png" alt="Response-time distribution" width="48%">
  <img src="out/RQ2_architecture_metrics/gpt-4o-mini/RQ2_per_response_distribution_total_input_tokens.png" alt="Input-token consumption distribution" width="48%">
</p>
<p align="center">
  <img src="out/RQ2_architecture_metrics/gpt-4o-mini/RQ2_per_response_distribution_llm_call_count.png" alt="LLM-call-count distribution" width="48%">
  <img src="out/RQ2_architecture_metrics/gpt-4o-mini/RQ2_answer_code_lines_violin_distribution.png" alt="Answer-size distribution in lines of code" width="48%">
</p>

### RQ3 - Predictability

RQ3 combines execution-level trace consistency with human-reviewed semantic clustering of final answers. The corresponding [trace-consistency workbook](out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_and_node_usage_consistency.xlsx) and [reviewed clustering results](out/RQ3_clustering/) provide the underlying data.

**Execution-level predictability**

<p align="center">
  <img src="out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_presence_heatmap.png" alt="Agentic tool-presence heatmap" width="48%">
  <img src="out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_node_usage_consistency_presence_heatmap.png" alt="Graph-based node-presence heatmap" width="48%">
</p>

**Answer-level predictability**

<p align="center">
  <img src="out/RQ3_clustering/RQ3_clustering_reviewed_overall_mean_majority_share.png" alt="Mean majority-cluster share" width="48%">
  <img src="out/RQ3_clustering/RQ3_clustering_reviewed_overall_perfect_consensus_rate.png" alt="Perfect-consensus rate" width="48%">
</p>
<p align="center">
  <img src="out/RQ3_clustering/RQ3_clustering_reviewed_overall_mean_cluster_count.png" alt="Mean cluster count" width="48%">
  <img src="out/RQ3_clustering/RQ3_clustering_reviewed_overall_fallback_rate.png" alt="Fallback rate" width="48%">
</p>

### RQ4 - Guardrail effectiveness

The combined RQ4 experiment contains 20 runs x 15 prompts x 3 architectures for each of four models. Its [combined workbook](out/RQ4_guardrail_metrics/RQ4_guardrail_metrics.xlsx), [architecture summary](out/RQ4_guardrail_metrics/rq4_architecture_summary.csv), and [prompt/architecture summary](out/RQ4_guardrail_metrics/rq4_prompt_arch_summary.csv) contain the detailed results.

<p align="center">
  <img src="out/RQ4_guardrail_metrics_judged/RQ4_guardrail_blocked_counts.png" alt="Blocked responses by architecture and model" width="48%">
  <img src="out/RQ4_guardrail_metrics_judged/RQ4_guardrail_prompt_block_rate_heatmap.png" alt="Prompt-level block rate by architecture and model" width="48%">
</p>

### Raw data and provenance
Raw execution workbooks and tracing exports are retained under [`out/runs/`](out/runs/), organized as `<model-label>/<experiment>/<run-group-id>/`. The append-only raw log is [`out/results.jsonl`](out/results.jsonl). Prompt catalogs and architecture configuration used to generate the experiments are in [`configs/`](configs/).

Reproducing and Extending the Experiments
------------------------------------------

The sections below describe how to install the project, configure it, run new executions, and regenerate each analysis artifact. They are not required to inspect the published results above.

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

You can set the default execution model label once at the top level:

```json
{
  "model_label": "gpt-4.1-mini",
  "architectures": [
    { "...": "..." }
  ]
}
```

`model_label` is used by `python -m app.main` to decide where runs are stored
under `out/runs/<model_label>/...`. It does not by itself force the downstream
architecture projects to change model; those projects still need to read the
real model from their own config/env. The CLI flag `--model-label` still exists
and overrides the JSON value when you need a one-off run.

You can also avoid repeating shared architecture fields by using top-level
`variables` and `defaults`. String values support placeholders like `{cwd}` and
`{automation_root}`:

```json
{
  "model_label": "gpt-4.1-mini",
  "variables": {
    "automation_root": "/home/ivan/miso/automatizacion"
  },
  "defaults": {
    "cwd": "{automation_root}/{project_dir}",
    "cmd": ["{cwd}/.venv/bin/python", "-m", "app.main"],
    "env_file": "{automation_root}/configs/.env"
  },
  "architectures": [
    { "id": "agentic_architecture", "project_dir": "agentic" },
    { "id": "graph_based_architecture", "project_dir": "graph" },
    { "id": "one_node_architecture", "project_dir": "one-node" }
  ]
}
```

The older fully expanded format still works.

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
python -m app.main -rq2 -r 5
python -m app.main -rq2 -r 5 --model-label gpt-5-codex
```

Important flags:

- `-r, --runs`: number of repeated executions
- `-v, --verbose`: verbose logging
- `--model-label`: optional override for the model label defined in `configs/architectures.json`

Execution Outputs
-----------------

Every run writes:

- `out/results.jsonl`: append-only raw run log
- `out/runs/<experiment>/<run_group_id>/results.xlsx`: legacy/default layout
- `out/runs/<model_label>/<experiment>/<run_group_id>/results.xlsx`: model-scoped layout when `--model-label` is used

`<run_group_id>` is timestamp-based, so each execution batch gets its own folder.
For `-rq2`, `<experiment>` is `architecture_comparison`.

The generated results also include `is_yaml_valid` for prompt types that expect YAML, plus `model_label` and `model_slug` metadata columns.

Analysis Workflows
------------------

RQ1: Ranking Sheets
-------------------

Generate the randomized ranking package:

```bash
python -m app.rq1.generate_rankings
python -m app.rq1.generate_rankings --model-label gpt-5-codex
```

This reads the first run folder under `out/runs/architecture_comparison/` by
default. With `--model-label`, it reads from
`out/runs/<model-label>/architecture_comparison/`.
You can override the selected run with `--run-id` or bypass the default lookup
with `--runs-dir`.

Main outputs go to:

- `out/RQ1/<run_id>/` for the legacy/default layout
- `out/RQ1/<model-label>/<run_id>/` when `--model-label` is used

Files:

- `ranking.md`
- `key.csv`
- `answers.csv`

The generated `answers.csv` template includes:

- `rank1`, `rank2`, `rank3`, ...
- `confidence`, which must be filled with `H`, `M`, or `L`
- when completed, save it as `answers_<rater>.csv` so aggregation picks it up

Aggregate completed subject answers:

```bash
python -m app.rq1.aggregate_rankings
python -m app.rq1.aggregate_rankings --model-label gpt-5-codex --run-id 20260423_120000_000
```

Useful flags:

- `--run-id <run_id>`
- `--model-label <label>`
- `--answers-dir <path>`

Main aggregate outputs:

- `combined_rankings.csv`
- `metrics_avg_prompt_rank.csv`
- `metrics_pairwise.csv`
- `metrics_position_distribution.csv`
- `metrics_friedman.csv`
- `metrics_interrater_by_prompt.csv`
- `metrics_interrater_summary.csv`
- `RQ1_weighted_avg_prompt_rank.png`
- `RQ1_pairwise_summary.png`
- `RQ1_position_distribution.png`

RQ2: Architecture Metrics Aggregation
-------------------------------------

Aggregate metrics across execution runs:

```bash
python -m app.rq2
python -m app.rq2 --model-label gpt-4.1-mini
```

This produces the main RQ2 workbook and plots from the execution results.
With `--model-label`, it reads from
`out/runs/<model-label>/architecture_comparison/` and writes to
`out/RQ2_architecture_metrics/<model-label>/`.

The RQ2 workbook includes:

- aggregated per-architecture metrics
- pairwise Wilcoxon signed-rank tests on matched `run_group_id + prompt_id` rows

RQ2 model comparison plots:

```bash
python -m app.rq2 --model-comparison-only
```

This writes combined multi-model plots and tabular summaries to
`out/RQ2_architecture_metrics/model_comparison/`. The plots keep the same RQ2
metric families but group the X axis by model and draw one architecture series
inside each model group. Per-model plots in
`out/RQ2_architecture_metrics/<model-label>/` are left unchanged.

Architecture footprint snapshot:

```bash
python app/rq2/architecture_footprint.py
```

This writes `out/RQ2_architecture_metrics/architecture_footprint.csv` with `SLOC`-based Python source counts and also prints the CSV rows to stdout.
The script expects a sibling checkout at `../Senpai-Assistant` relative to this repository.

Supplementary fallback/answer join:

```bash
python app/rq2/fallback_answer_join.py
python app/rq2/fallback_answer_join.py --model-label gpt-5-codex
```

This writes:

- `out/RQ2_architecture_metrics/rq2_fallback_answers_joined.xlsx`

Useful flags for the join script:

- `--model-label`
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
python -m app.rq3_consistency --model-label gpt-4o-mini
```

Default input:

- `out/runs/advanced_prompt_arch_comparison/`
- `out/runs/<model-label>/advanced_prompt_arch_comparison/` when `--model-label` is used

Default output directory:

- `out/RQ3_tool_consistency_and_node_usage_consistency/`
- `out/RQ3_tool_consistency_and_node_usage_consistency/<model-label>/` when `--model-label` is used

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
python -m app.rq3_clustering --model-label gpt-4o-mini
```

Default input:

- `out/runs/advanced_prompt_arch_comparison/`
- `out/runs/<model-label>/advanced_prompt_arch_comparison/` when `--model-label` is used

Default output directory:

- `out/RQ3_clustering/`
- `out/RQ3_clustering/<model-label>/` when `--model-label` is used

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

RQ4: Guardrail Test Metrics
---------------------------

Run the RQ4 guardrail analysis pipeline:

```bash
python -m app.rq4
python -m app.rq4 --model-label gpt-4o-mini
```

Default input:

- `out/runs/<model-label>/guardrail_test/` for every discovered model folder when no `--model-label` or `--runs-dir` is provided
- `out/runs/guardrail_test/`
- `out/runs/<model-label>/guardrail_test/` when `--model-label` is used

Default output directory:

- `out/RQ4_guardrail_metrics/` for the combined multi-model report or legacy non-model runs
- `out/RQ4_guardrail_metrics/<model-label>/` when `--model-label` is used

This workflow reads repeated `guardrail_test` execution workbooks, merges them
with the `configs/rq4_prompts.json` prompt catalog, classifies each final answer
as an effective allow/block decision, and compares the observed behavior against
the expected guardrail outcome for each prompt.

Main outputs:

- `RQ4_guardrail_metrics.xlsx`
- architecture and prompt-level CSV summaries
- `RQ4_guardrail_prompt_block_rate_heatmap.png`
- `RQ4_guardrail_blocked_counts.png`, grouped by model with one bar per architecture when multiple models are discovered

Useful flags:

- `--model-label`
- `--runs-dir`
- `--runs-root`
- `--out-dir`

RQ4: LLM-as-a-Judge Fallback Cleanup
------------------------------------

Use LangChain judges to re-label whether each RQ4 answer actually complied
with the guardrail:

```bash
python -m app.rq4.judge_fallbacks --env-file .env
python -m app.rq4 --runs-root out/RQ4_guardrail_judged_fallbacks/corrected_runs
```

The judge reads every discovered `results.xlsx`, evaluates the original prompt
and answer, and writes corrected copies without modifying the original runs.

Main outputs:

- `out/RQ4_guardrail_judged_fallbacks/RQ4_judged_fallbacks.xlsx`
- `rq4_judged_fallback_rows.csv`
- `rq4_judged_fallback_summary.csv`
- `corrected_runs/<model-label>/guardrail_test/<run>/results.xlsx`

Useful flags:

- `--providers openai gemini`
- `--openai-model`
- `--gemini-model`
- `--only-original-nonfallback`
- `--decision-policy any-bypass`
