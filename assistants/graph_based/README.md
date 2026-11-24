# Senpai: graph-based routed variant

This variant of Senpai implements the graph-based routed architecture as a LangGraph workflow. An intent-routing node classifies the request into one of seven intents (create or fix a profile, rule or connector, or explain), or rejects it as out of scope. The corresponding task-specific node then prompts the LLM with only the documentation and examples relevant to that task. If the answer contains code, it is validated with the [`senpai-validators`](https://pypi.org/project/senpai-validators/) parsers and, when invalid, repaired in a loop of up to three attempts before a fallback message is returned.

Main modules:

- `app/main.py`, `app/CLI/cli.py`: command-line entry point.
- `app/assistant/graph.py`: definition of the workflow graph.
- `app/nodes/node_intent_routing.py`: intent routing and scope check.
- `app/nodes/answer/`: the seven task-specific nodes.
- `app/nodes/action/`: code-block detection, validation decision, validation, repair and fallback nodes.
- `app/assistant/prompt.py`, `app/assistant/project_context.py`, `app/assistant/validation.py`: prompt construction, context loading and validation.

See [`../README.md`](../README.md) for provenance and instructions to run it.
