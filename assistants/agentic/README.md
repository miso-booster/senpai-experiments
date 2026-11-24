# Senpai: agentic variant

This variant of Senpai implements the agentic architecture as a LangChain agent. The agent decides which of its 16 tools to call to address a request: a tool that retrieves the documentation and examples of the requested artefact types, and, for each artefact type (profiles, rules and connectors), tools to list, read, save and delete artefacts and to search them by embedding similarity. A middleware stack wraps the agent with a scope guardrail, task planning, conversation summarisation, a validation decision and the enforcement of validation (with the [`senpai-validators`](https://pypi.org/project/senpai-validators/) parsers and at most two repair attempts), and human-in-the-loop approval of write and delete actions.

When run with `--single-turn-prompt`, as in the experiments, the three save tools are disabled (leaving 13 tools) so that generated artefacts are returned in the answer instead of through human-in-the-loop tool calls.

Main modules:

- `app/main.py`, `app/CLI/cli.py`: command-line entry point.
- `app/assistant/agent.py`, `app/assistant/assistant.py`: agent construction and LLM configuration.
- `app/assistant/tools.py`: the agent tools.
- `app/embeddings/`: embedding index of the project artefacts and similarity search.
- `app/assistant/scope_guardrail_middleware.py`, `app/assistant/validation_middleware.py`, `app/assistant/hitl_feedback_middleware.py`: guardrail, validation and human-in-the-loop middleware.
- `app/assistant/prompt.py`, `app/assistant/conversation.py`: system prompt and conversation handling.

See [`../README.md`](../README.md) for provenance and instructions to run it, and [`docs/architecture/`](../../docs/architecture/) for its architecture.
