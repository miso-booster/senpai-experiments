# Senpai: monolithic single-prompt variant

This variant of Senpai implements the monolithic single-prompt architecture. Each request is answered with a single LLM call, whose prompt contains the description of the supported tasks, the documentation and examples of all Dojo artefact types (`app/docs/`), all artefacts of the current Dojo project and user folder, the conversation history, and the user request. The answer is returned to the user without validation.

Main modules:

- `app/main.py`, `app/CLI/cli.py`: command-line entry point.
- `app/assistant/assistant.py`, `app/assistant/graph.py`: LLM configuration and the one-node LangGraph workflow.
- `app/nodes/answer/node_prompt.py`: the single answering node.
- `app/assistant/prompt.py`, `app/assistant/project_context.py`: prompt construction and loading of the project and user context.

See [`../README.md`](../README.md) for provenance and instructions to run it.
