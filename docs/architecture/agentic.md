# Agentic variant

Source code: [`assistants/agentic/`](../../assistants/agentic/). Back to the [overview](README.md).

This variant implements the agentic reference architecture with LangChain's `create_agent`. The agent runs a loop in which the LLM decides which tools to call, retrieving documentation and project artefacts on demand. A stack of middleware wraps the loop with a scope guardrail, planning, summarisation, validation with repair, and human approval of write and delete actions.

## Component view

```mermaid
flowchart TB
    user([User or harness])
    subgraph senpai["Senpai agentic variant (assistants/agentic/app)"]
        cli["CLI and conversation runner<br/>main.py, assistant/conversation.py"]
        asst["Assistant runtime<br/>assistant/assistant.py"]
        subgraph agent["Agent with middleware (assistant/agent.py)"]
            guard["Scope guardrail<br/>before agent"]
            pre["Planning (write_todos)<br/>and summarisation<br/>before model"]
            loop["Agent loop<br/>model calls and tool calls"]
            post["Validation decision and validation,<br/>human-in-the-loop<br/>after model"]
            guard --> pre --> loop --> post
            post -->|repair or rejection feedback| loop
        end
        tools["Project tools<br/>assistant/tools.py"]
        emb["Embedding index and search<br/>embeddings/"]
        val["Validation wrapper<br/>assistant/validation.py"]
    end
    llm{{"LLM<br/>agent reasoning, scope check,<br/>summaries, validation decisions, repairs"}}
    docs[["Domain documentation<br/>app/docs/*.md"]]
    ws[["Dojo workspace<br/>project profiles and rules,<br/>user connectors"]]
    pv[["senpai-validators<br/>DSL parsers"]]

    user -->|request| cli --> asst --> guard
    loop -->|tool calls| tools
    tools -.-> docs
    tools -.-> ws
    tools -.-> emb -.-> ws
    post -.-> val -.-> pv
    agent -->|LLM calls| llm
    post -->|"approval requests, answer"| user

    subgraph legend["Legend"]
        direction LR
        la[" "]:::ghost -->|request processing| lb[" "]:::ghost
        lc[" "]:::ghost -.->|uses or reads| ld[" "]:::ghost
    end
    pv ~~~ legend
    classDef ghost fill:none,stroke:none
    style legend fill:#f2f2f2,stroke:#888
```

## Components

| Component | Module | Responsibility |
|---|---|---|
| CLI and conversation runner | `main.py`, `CLI/cli.py`, `assistant/conversation.py` | Arguments, single turn or conversation, resolution of pending approvals, answer between `$$$` delimiters. With `-stp` (the experiments), the save tools are not registered. |
| Assistant runtime | `assistant/assistant.py` | Initialises the chat model (temperature 0.3, `SENPAI_MODEL*` variables), the SQLite checkpointer, the embedding indexes and the agent. Sends messages and resumes interrupted runs. |
| Agent | `assistant/agent.py`, `assistant/prompt.py` | Builds the tools, the middleware stack and the agent, whose system prompt describes the assistant and how to use the tools. Unlike the other variants, the system prompt contains no documentation. |
| Project tools | `assistant/tools.py` | 16 tools: `get_docs` (documentation and examples of the requested artefact types), and for profiles, rules and connectors, `list_*`, `read_*`, `search_*` (similarity search), `save_*` and `delete_*`. |
| Embedding index and search | `embeddings/` | Builds and refreshes an embedding index of the project's profiles and rules and of the user's connectors, and answers the `search_*` tools. |
| Scope guardrail | `assistant/scope_guardrail_middleware.py` | Before the agent runs, classifies the request as in or out of scope with an LLM structured-output call. Out-of-scope requests get an LLM-written refusal and end the run. If the classifier fails, the request is allowed. |
| Planning | `TodoListMiddleware` (LangChain) | Adds the `write_todos` tool and instructions to keep an explicit to-do list for rule, profile and connector requests. The agent decides when to call it. |
| Summarisation | `SummarizationMiddleware` (LangChain) | Summarises older messages when the context reaches 85% of the model window. |
| Validation decision | `assistant/validation_middleware.py` (`ValidationDecisionMiddleware`) | If the model's reply contains YAML or a save tool call, asks the LLM whether validation is required. |
| Tool-call validation | `ToolCallValidationMiddleware` | Validates the YAML passed to `save_*` tools before they run, and returns the errors to the agent. Inactive in the experiments, since the save tools are disabled. |
| Message validation and repair | `MessageValidationMiddleware`, `assistant/validation.py` | Validates the YAML blocks of the final reply with `senpai-validators`. If they are invalid, adds the relevant documentation and the errors, and asks the LLM for a corrected reply; after the third failed validation, replaces the reply with an LLM-written failure message. |
| Human-in-the-loop | `HumanInTheLoopMiddleware` (LangChain), `assistant/hitl_feedback_middleware.py` | Interrupts the run before `save_*` and `delete_*` tool calls until the user approves, edits or rejects them, and feeds rejections back to the agent. |

LangChain runs `after_model` middleware in reverse order of declaration, so after each model call the validation middleware runs before the human-in-the-loop middleware.

## Interaction view: "create a rule" with an invalid first answer

```mermaid
sequenceDiagram
    autonumber
    actor U as User / harness
    participant G as Scope guardrail
    participant A as Agent loop
    participant T as Tools
    participant M as Validation middleware
    participant P as senpai-validators
    participant L as LLM
    U->>G: "Create a rule that checks ..."
    G->>L: in scope? (structured output)
    L-->>G: in_scope = true
    G->>A: continue
    A->>L: system prompt + request + tool descriptions
    L-->>A: call write_todos, get_docs(["rules"]), list_rules
    A->>T: run tool calls
    T-->>A: to-do list, rule guide and examples, project rules
    A->>L: conversation with tool results
    L-->>A: reply with YAML rule
    A->>M: after-model hooks
    M->>L: does this reply need validation?
    L-->>M: yes
    M->>P: validate rule YAML
    P-->>M: errors
    M->>L: reply + reference docs + errors (validation 1 of 3)
    L-->>M: corrected reply
    M->>P: validate rule YAML
    P-->>M: valid
    M-->>U: corrected reply
```

The tools called, and their order, are chosen by the LLM and vary between runs; the sequence above is one typical path. If a run had called a `delete_*` tool, the human-in-the-loop middleware would have interrupted it and asked the user for approval before executing the call.
