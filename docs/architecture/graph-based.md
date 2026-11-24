# Graph-based routed variant

Source code: [`assistants/graph_based/`](../../assistants/graph_based/). Back to the [overview](README.md).

This variant implements the graph-based routed reference architecture as a LangGraph state machine with 14 nodes. An intent router selects one of seven task-specific nodes, each with its own prompt and context. The answer then goes through a validation pipeline with a repair loop.

## Component view

```mermaid
flowchart LR
    user([User or harness])
    subgraph senpai["Senpai graph-based variant (assistants/graph_based/app)"]
        cli["CLI<br/>main.py, CLI/cli.py"]
        asst["Assistant runtime<br/>assistant/assistant.py"]
        subgraph wf["LangGraph workflow (assistant/graph.py)"]
            router["Intent router<br/>nodes/node_intent_routing.py"]
            tasks["7 task nodes<br/>nodes/answer/"]
            qa["Validation and repair nodes<br/>nodes/action/"]
        end
        ctx["Task prompts and per-intent context<br/>assistant/prompt.py, project_context.py"]
        val["Code-block handling and validation<br/>assistant/codeblocks.py,<br/>codeblock_classifier.py, validation.py"]
    end
    llm{{"LLM"}}
    docs[["Domain documentation<br/>app/docs/*.md"]]
    ws[["Dojo workspace<br/>project profiles and rules,<br/>user connectors"]]
    pv[["senpai-validators<br/>DSL parsers"]]

    user -->|request| cli --> asst --> router
    router --> tasks --> qa
    tasks -.-> ctx
    ctx -.-> docs
    ctx -.-> ws
    qa -.-> val -.-> pv
    wf -->|"classify, generate, decide,<br/>repair, failure message"| llm
    qa -->|answer| user

    subgraph legend["Legend"]
        direction LR
        la[" "]:::ghost -->|request processing| lb[" "]:::ghost
        lc[" "]:::ghost -.->|uses or reads| ld[" "]:::ghost
    end
    classDef ghost fill:none,stroke:none
```

## Workflow

The 14 nodes and their transitions, as defined in `assistant/graph.py`:

```mermaid
flowchart TD
    start([START]) --> classify["classify_request<br/>(LLM)"]
    classify -->|other| endOut(["END: fixed out-of-scope message"])
    classify -->|create_profile, create_rule, create_connector,<br/>fix_profile, fix_rule, fix_connector, explain| task["one of 7 task nodes<br/>(LLM)"]
    task --> decide["decide_validation<br/>(LLM, only for create/fix intents)"]
    decide --> detect["detect_code_blocks"]
    detect -->|no validation needed<br/>or no code block| endOk(["END: answer"])
    detect -->|code blocks| extract["extract_code_blocks"]
    extract --> validate["validate_code_blocks"]
    validate -->|valid| endOk
    validate -->|invalid, fewer than 3 validations| fix["fix_code_blocks<br/>(LLM repair)"]
    fix --> detect
    validate -->|invalid, 3rd validation| failure["render_failure<br/>(LLM)"]
    failure --> endFail(["END: fallback message"])
```

## Components

| Component | Module | Responsibility |
|---|---|---|
| CLI | `main.py`, `CLI/cli.py` | As in the other variants: arguments, single turn or conversation, answer between `$$$` delimiters. |
| Assistant runtime | `assistant/assistant.py` | Initialises the chat model, the optional SQLite checkpointer, the per-intent context and the graph, and streams the graph. |
| Intent router | `nodes/node_intent_routing.py`, `assistant/intent.py` | Asks the LLM to classify the latest request into `create_rule`, `create_profile`, `create_connector`, `fix_rule`, `fix_profile`, `fix_connector`, `explain` or `other` (JSON answer). `other` ends the workflow with a fixed message. |
| Task nodes | `nodes/answer/node_*.py` | One node per intent. Each prompts the LLM with its task-specific system prompt and context, plus the conversation. |
| Task prompts | `assistant/prompt.py` | Profile nodes get `sensei-chat-guide.md`; rule nodes get `sensei-check-doc.md`; connector nodes get `connector-examples.md` and `custom-connector-guide.md`; the explain node gets all five files. |
| Per-intent context | `assistant/project_context.py` | Loads the project's profiles and rules and the user's connectors. Profile, rule and connector nodes receive only the artefacts of their type; the explain node receives all of them. |
| Validation decision | `nodes/action/node_decide_validation_needed.py` | For create and fix intents, asks the LLM whether the user wants a validated answer (e.g., not when a broken artefact is requested on purpose). Defaults to validating. |
| Code-block detection and extraction | `nodes/action/node_detect_code_blocks.py`, `node_extract_codeblocks_metadata.py`, `assistant/codeblocks.py`, `assistant/codeblock_classifier.py` | Finds fenced code blocks in the answer, splits YAML documents and classifies them heuristically as profile, rule or connector. |
| Validation | `nodes/action/node_validate_code_blocks_content.py`, `assistant/validation.py` | Validates each block with the corresponding `senpai-validators` parser, counts the attempts and decides between ending, repairing and failing. |
| Repair | `nodes/action/node_fix_invalid_code_blocks.py`, `node_build_fix_system_prompt.py` | Asks the LLM to correct the invalid blocks, given the validator feedback. Its system prompt contains all five documentation files and the artefacts of the routed intent's type, and asks for the corrected code block only. The repaired answer goes through detection and validation again. |
| Failure message | `nodes/action/node_render_validation_failure_response.py` | After the third failed validation, asks the LLM to write a fallback message for the user instead of returning invalid code. |

## Interaction view: "create a rule" with an invalid first answer

```mermaid
sequenceDiagram
    autonumber
    actor U as User / harness
    participant R as Intent router
    participant T as create_rule node
    participant D as Validation decision
    participant V as Detection, extraction and validation
    participant F as Repair node
    participant P as senpai-validators
    participant L as LLM
    U->>R: "Create a rule that checks ..."
    R->>L: classify intent
    L-->>R: {"intent": "create_rule"}
    R->>T: route
    T->>L: rule prompt (rule guide + project rules) + conversation
    L-->>T: answer with YAML rule
    T->>D: answer
    D->>L: should this answer be validated?
    L-->>D: {"decision": "TRUE"}
    D->>V: answer
    V->>P: validate rule YAML
    P-->>V: errors
    V->>F: invalid blocks + feedback (validation 1 of 3)
    F->>L: repair prompt
    L-->>F: corrected answer
    F->>V: corrected answer
    V->>P: validate rule YAML
    P-->>V: valid
    V-->>U: corrected answer
```

In this example, the request takes four LLM calls: routing, generation, validation decision and one repair.
