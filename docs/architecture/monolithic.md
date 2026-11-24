# Monolithic single-prompt variant

Source code: [`assistants/one_node/`](../../assistants/one_node/). Back to the [overview](README.md).

This variant implements the monolithic single-prompt reference architecture: every request is answered by one LLM call whose prompt contains all the information that might be relevant. It has no explicit routing, validation or repair, and serves as the baseline of the comparison.

## Component view

```mermaid
flowchart LR
    user([User or harness])
    subgraph senpai["Senpai monolithic variant (assistants/one_node/app)"]
        cli["CLI<br/>main.py, CLI/cli.py"]
        asst["Assistant runtime<br/>assistant/assistant.py"]
        onegraph["One-node LangGraph<br/>assistant/graph.py"]
        node["Answer node<br/>nodes/answer/node_prompt.py"]
        prompt["Prompt builder<br/>assistant/prompt.py"]
        ctx["Context loader<br/>assistant/project_context.py"]
        mem[("Conversation checkpoints<br/>SQLite")]
    end
    docs[["Domain documentation<br/>app/docs/*.md (all 5 files)"]]
    proj[["Dojo project<br/>profiles, rules"]]
    usr[["Dojo user folder<br/>connectors"]]
    llm{{"LLM"}}

    user -->|request| cli --> asst --> onegraph --> node
    asst --- mem
    node --> prompt
    node --> ctx
    prompt --> docs
    ctx --> proj
    ctx --> usr
    node -->|one call| llm
    node -->|answer| user
```

## Components

| Component | Module | Responsibility |
|---|---|---|
| CLI | `main.py`, `CLI/cli.py` | Parses the arguments, creates the assistant, runs one turn (`-stp`) or an interactive conversation, and prints the answer between `$$$` delimiters. |
| Assistant runtime | `assistant/assistant.py` | Initialises the chat model (`init_chat_model`, temperature 0.3, `SENPAI_MODEL*` variables), the optional SQLite checkpointer, and the graph. Streams the graph and returns the last AI message. |
| One-node graph | `assistant/graph.py` | LangGraph `START -> respond -> END`. |
| Answer node | `nodes/answer/node_prompt.py` | Builds the system prompt, prepends it to the conversation messages and invokes the LLM once. |
| Prompt builder | `assistant/prompt.py` | Task description (create, fix and explain profiles, rules and connectors, and scope instructions) followed by the full content of the five documentation files. |
| Context loader | `assistant/project_context.py` | Reads all YAML files of the Dojo project (profiles, rules) and of the user folder (connectors) and formats them as prompt sections. |

The folder `app/validator/` contains an earlier copy of the DSL parsers, which only the tests use. The answer is never validated.

## Interaction view: "create a rule"

```mermaid
sequenceDiagram
    autonumber
    actor U as User / harness
    participant C as CLI + Assistant runtime
    participant N as Answer node
    participant P as Prompt builder + context loader
    participant L as LLM
    U->>C: "Create a rule that checks ..." (-stp)
    C->>N: graph.stream(messages)
    N->>P: build system prompt
    P-->>N: task description + 5 docs + all profiles, rules and connectors
    N->>L: system prompt + conversation
    L-->>N: answer (text, possibly with YAML)
    N-->>C: AI message
    C-->>U: answer between $$$ delimiters
```

Out-of-scope requests follow the same path: whether to refuse is decided by the LLM itself, following the scope instructions of the system prompt.
