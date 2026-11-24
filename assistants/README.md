# Senpai assistant variants

This folder contains the source code of the three variants of Senpai, the assistant of the Chatbot Dojo platform, that were evaluated in the experiments of this repository. Each variant implements one of the three architectures compared in the paper.

| Folder | Architecture (paper) | Main technology |
|---|---|---|
| [`one_node/`](one_node/) | Monolithic single-prompt | LangGraph 0.6 / LangChain 0.3; a single LLM node |
| [`graph_based/`](graph_based/) | Graph-based routed | LangGraph 0.6 / LangChain 0.3; intent router, task nodes, validation and repair loop |
| [`agentic/`](agentic/) | Agentic | LangChain 1.1 / LangGraph 1.0; agent with tools, embedding search, middleware and human-in-the-loop |

The folder names match the `project_dir` values in [`../configs/architectures.json`](../configs/architectures.json).

## Provenance

The code is a snapshot of the private development repository, taken at the commits used for the experiments reported in the paper. These commits include the patch that lets the LLM be selected through environment variables, which was used for the `deepseek-chat` runs.

| Folder | Source branch | Commit |
|---|---|---|
| `one_node/` | `one-node-based-assistant` | `a9b8c87` |
| `graph_based/` | `graph-based-assistant` | `2dfe25f` |
| `agentic/` | `agentic-assistant` | `4b61f33` |

The code, the documentation injected into the prompts (`app/docs/`), the Dojo test projects used as context (`sensei_projects/`), the Dojo user folder with its connectors (`users/user_1/`), the tests, and the locked dependencies (`uv.lock`) are unchanged. The following files of the development repository were left out because they are not needed to run or understand the variants:

- internal development notes (the original `README.md`, `docs/PRD.md`, `docs/metrics_senpai.md`);
- the GitHub CI workflows (`.github/`);
- precomputed embedding indexes (`app/embedding_files/*/*.pkl`), which are not used by the graph-based variant and are rebuilt automatically by the agentic variant.

The DSL parsers used for syntactic validation are distributed as the [`senpai-validators`](https://pypi.org/project/senpai-validators/) package (version 0.2.1), which the graph-based and agentic variants install from PyPI. The monolithic variant does not validate or repair its answers: its `app/validator/` folder holds an earlier copy of the parsers that only its tests use.

## Running a variant

Each variant is an independent Python 3.12 project. To install one, use [uv](https://docs.astral.sh/uv/) with the locked dependencies (do not upgrade them, since that changes the LangChain stack):

```bash
cd assistants/<variant>
uv sync --frozen
```

By default, the variants use `gpt-4o-mini` and read `OPENAI_API_KEY` from the environment. Another model can be selected with the `SENPAI_MODEL`, `SENPAI_MODEL_PROVIDER`, `SENPAI_MODEL_BASE_URL` and `SENPAI_MODEL_API_KEY` variables (see the main [README](../README.md#4-running-with-other-models-deepseek)). For providers that don't support JSON-schema structured outputs, the agentic variant also needs `SENPAI_STRUCTURED_OUTPUT_METHOD=function_calling`.

A single request can be run from the command line, as the experiment harness does:

```bash
.venv/bin/python -m app.main -pp sensei_projects/pizza_shop -up users/user_1 -stp "Create a rule that checks that pizza prices depend on their size"
```

On Windows, use `.venv\Scripts\python`. To run the experiments with these variants, set the `cwd` default in `configs/architectures.json` to `{automation_root}/assistants/{project_dir}`.
