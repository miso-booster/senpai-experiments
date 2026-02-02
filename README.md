Automated Prompt Interface
==========================

Small runner that loads architectures and prompts from `configs/` and executes
each prompt against each architecture, saving results to `out/`.

Requirements
------------
- Python 3.12+
- uv (Python package manager)

Install dependencies (uv)
-------------------------
If you don't have `uv` installed yet, install it with one of these:

```powershell
# Option A: pipx (recommended if available)
pipx install uv

# Option B: pip
python -m pip install --user uv
```

Then install project dependencies:

```powershell
uv sync
```

Run
---
```powershell
uv run python -m app.main
```

Optional verbose logging:

```powershell
uv run python -m app.main -v
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
- Per-group CSV: `out/runs/<run_group_id>/results.csv`

Ranking sheets (offline evaluation)
----------------------------------
Generate a randomized ranking markdown + key + answers template:

```powershell
uv run python -m app.generate_rankings --run-group-id <run_group_id>
```

This writes to `out/runs/<run_group_id>/ranking/` (CSV delimiter is `;`):
- `ranking.md` (responses randomized per prompt)
- `key.csv` (label -> arch/run mapping)
- `answers.csv` (template to fill in ranks)

Aggregate multiple subjects (expects `answers_*.csv` and `key.csv`):

```powershell
uv run python -m app.aggregate_rankings --answers-dir out/runs/<run_group_id>/ranking
```

This also writes metrics CSVs in the same folder:
- `metrics_overall.csv` (per-architecture avg rank, Borda, win rate)
- `metrics_per_prompt.csv` (per-prompt avg rank + win rate)
- `metrics_pairwise.csv` (pairwise win rates)

Output structure per execution
------------------------------
Each execution writes to:

- `out/results.jsonl` (append-only): one JSON line per architecture/prompt run.
- `out/runs/<run_group_id>/results.csv`: a snapshot for that execution only.

`<run_group_id>` is a timestamp with milliseconds, so each execution gets its own
folder under `out/runs/`.

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
