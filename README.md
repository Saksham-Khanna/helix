# Helix — Terminal Coding Agent

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/tests-58%20passed-brightgreen)
![No Framework](https://img.shields.io/badge/built%20without-LangChain%20%2F%20AutoGen-orange)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)
![Stars](https://img.shields.io/github/stars/Saksham-Khanna/terminal-assistant?style=social)
[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/Sakshamm-Khanna.helix-terminal-ai?label=VS%20Marketplace)](https://marketplace.visualstudio.com/items?itemName=Sakshamm-Khanna.helix-terminal-ai)
[![Installs](https://img.shields.io/visual-studio-marketplace/i/Sakshamm-Khanna.helix-terminal-ai)](https://marketplace.visualstudio.com/items?itemName=Sakshamm-Khanna.helix-terminal-ai)

> **Claude Code / Cursor / Aider jaise tools kaise kaam karte hain — ye project usko scratch se dikhata hai.** LLM agent loop + tool-calling + RAG, bina kisi agent framework ke. Terminal me direct use karo.

**No credit card, no cost — Gemini free tier + Groq free tier + Ollama local (qwen2.5:7b) pe chalta hai.**

---

## Demo

![Helix Demo](assets/demo.gif)

*20s — `python cli.py chat` — `read_file` → `edit_file` (diff) → `pytest` — `qwen2.5:7b` local*

```bash
python cli.py chat
# you> Fix the divide-by-zero bug in sample.py
# agent> [read_file] [edit_file] [run_shell_command: pytest] -> Done
```

---

## Features

| Feature | Detail |
|---|---|
| **Agent Loop** | `LLM -> tool_use -> execute -> repeat` (`agent/core.py:189`), streaming support (`agent/core.py:239`), max 25 iterations |
| **Tools (10)** | `read_file`, `write_file`, `edit_file` (diff-based), `list_dir`, `grep_search`, `find_files_by_glob`, `read_file_range`, `run_shell_command`, `search_codebase`, `undo_last_change` (`agent/tools.py:42`) |
| **RAG Search** | AST-aware chunking (Tree-sitter) + `sentence-transformers` + Chroma vector store (`rag/indexer.py`, `rag/search.py`) |
| **Safety** | Project-root guard (`agent/tools.py:25` `AGENT_WORKSPACE` + `AGENT_READ_ONLY`), path-traversal block, Docker sandbox (`agent/sandbox.py:116`), auto-lint after edits (`agent/tools.py:360`) |
| **Session & Undo** | Save/resume conversations (`agent/session.py`), git shadow commits + instant `/undo` / `/diff` (`agent/checkpoint.py:100`) |
| **Config** | `agentic.toml` + `.env` layered config, `agentic setup` wizard (`cli.py:92`), multi-provider (Gemini/Groq/Ollama) (`agent/llm.py:141`) |
| **Cost Tracking** | Token + cost per call (`agent/cost.py`), `/stats` |

---

## Architecture

```
cli.py                  Entry point (index / chat / sessions / undo / diff / run)
agent/
  core.py               Agent loop: LLM -> tool_use? -> execute -> repeat
  llm.py                Thin wrapper around Gemini / Groq / Ollama APIs
  tools.py              Tool schemas + implementations (file I/O, grep, glob, shell, RAG)
  diff.py               Diff/patch editing: edit_file tool + unified-diff previews
  summarizer.py         Context-window summarization
  session.py            Session persistence (.sessions/)
  checkpoint.py         Git checkpointing & /undo rollback (project .git)
  sandbox.py            Docker sandbox for shell commands (fallback to local)
rag/
  store.py              Embedding model + Chroma setup
  indexer.py            AST-aware chunking + embedding
  search.py             Semantic search for search_codebase tool
workspace/              Legacy sandboxed demo dir (now AGENT_WORKSPACE=. by default)
tests/                  58 tests (pytest)
```

### How it works

1. **Agent loop** (`agent/core.py`): conversation ko Gemini/Groq pe bhejo with tool schemas. Model ne `function_call` manga toh local `execute_tool` chalao, result wapas feed karo — jab tak plain text reply na aaye.
2. **Tools** (`agent/tools.py`): saare file ops `WORKSPACE_ROOT` (`agent/config.py:46` `AGENT_WORKSPACE=.`) me jailed hain, `AGENT_READ_ONLY=true` pe write/edit/shell block. `edit_file` surgical diff deta hai, `write_file` pura overwrite. Har Python edit pe `ast.parse` lint (`agent/tools.py:360`).
3. **RAG** (`rag/`): `python cli.py index` project root ko Tree-sitter se chunk karta hai, embed karke Chroma me dalta hai. `search_codebase` tool semantic search deta hai.
4. **Checkpoint** (`agent/checkpoint.py`): har file change se pehle/after git commit (project `.git`) — `/undo` se instant rollback, `/diff` se diff dekho.

---

## Deep Dive — How This Project Handles Core Concerns

### 1. How to Handle Memory
Long chat se context window overflow na ho isliye 2-level memory hai:

*   **In-memory conversation** — `agent/core.py:68` `contents` (Gemini) + `groq_messages` (Groq). Har `run_stream()` `agent/core.py:239` pe `self._maybe_summarize()` `agent/core.py:172` call hota hai.
*   **Summarization (context budget)** — `agent/summarizer.py:197` `should_summarize_*` check karta hai `len(text)//4` chars-per-token `agent/summarizer.py:28` se. Budget default `50000` tokens `agent/config.py:58` (`agentic.toml: [context] budget_tokens`). Exceed hua toh purane turns ko LLM se summarize kara ke `agent/summarizer.py:209` `summarize_gemini/groq` me compress karta hai — `TAIL_TURNS=6` `agent/summarizer.py:35` recent turns hamesha untouched rakhta hai. Prompt `agent/summarizer.py:40` `SUMMARIZE_PROMPT` me task/goals, files modified, errors sab bullet me nikalta hai. Failure pe fallback: original contents return `agent/summarizer.py:228`.
*   **Session persistence** — `agent/session.py:31` `SessionManager` JSON me save karta hai `.sessions/<slug>.json` `agent/session.py:41`. `gemini_contents` + `groq_messages` + `turn_count` + `created_at/updated_at` `agent/session.py:95` store hota hai. `/save`, `/load`, `--continue` `cli.py:264` se resume hota hai, `list_sessions()` `agent/session.py:150` recent sort karke deta hai.

### 2. Where Output Gets Stored
Har output ka fixed jail hai — agent kabhi bhi project root se bahar nahi likh sakta:

| Output | Kahan | Code |
|---|---|---|
| Agent file edits | Project root `AGENT_WORKSPACE=.` (read-only by default, `AGENT_READ_ONLY=true`) — set `false` for writes | `agent/tools.py:25` `WORKSPACE_ROOT`, `_resolve()` `agent/tools.py:30` path traversal block |
| Session JSON | `.sessions/<session_id>.json` | `agent/session.py:18` `SESSIONS_DIR`, `agent/config.py:58` |
| RAG index | `rag_db/` (Chroma persistent) + `chroma` collections | `rag/store.py`, `rag/indexer.py` (`cli.py:253` `index_directory`) |
| Git checkpoints | Project `.git` — har `write_file/edit_file` se pehle & after auto-commit `agent/checkpoint.py:76` `create_checkpoint()` (legacy `workspace/.git` shadow) | `agent/checkpoint.py:18`, `agent/tools.py:226` |
| Eval history | `eval_history.json` (append-only) | `agent/eval_history.py`, `agent/eval.py:183` `record_evaluation()` |
| Costs | In-memory `SessionUsage` + `/stats` table | `agent/cost.py`, `agent/core.py:142` `_record_usage()` |

### 3. Tool Grounding
Model kabhi direct file/shell nahi chalata — sirf tool request karta hai, execution hum karte hain:

*   **Schemas** — `agent/tools.py:42` `TOOL_SCHEMAS` (10 tools) model ko dikhta hai. Har schema me `name/description/input_schema` `agent/tools.py:43` hai.
*   **Dispatch** — `agent/tools.py:376` `execute_tool(name, args)` string return karta hai, error bhi `Error: ...` ke roop me model ko feed hota hai `agent/tools.py:431` taaki self-correct kare (`agent/core.py:350` `_run_gemini_iteration`).
*   **Streaming** — `agent/core.py:258` `llm.stream()` se `tool_call` chunks collect hote hain, fir `agent/core.py:318` me `execute_tool` + `types.Part.from_function_response` `agent/core.py:339` se wapas LLM ko bheja jata hai. Groq ke liye `agent/core.py:396` `_run_groq_iteration` same.
*   **Grounding via RAG** — `search_codebase` `agent/tools.py:274` `rag/search.py` se top-k chunks score ke saath laata hai, `agent/core.py:336` me `context_chunks_used` me track hota hai taaki eval me use ho.

### 4. Guardrails
*   **Path jail** — `_resolve()` `agent/tools.py:30` `abspath` + `startswith(WORKSPACE_ROOT)` check, escape pe `ValueError`.
*   **Shell safety** — `SAFE_COMMAND_PREFIXES` `agent/tools.py:257` (`ls, cat, pytest, git status` etc.) auto-allow, baki pe `y/N` confirm `agent/tools.py:264`. Execution `agent/sandbox.py:116` `run_sandboxed()` Docker me `--read-only --cap-drop ALL --network none --memory 512m --cpus 2` `agent/sandbox.py:72` ke saath, Docker na ho toh local fallback `agent/sandbox.py:139` + timeout `agent/config.py:68`.
*   **Auto-lint** — `edit_file/write_file` ke baad `ast.parse` `agent/tools.py:360` `_check_python_syntax()`, error mila toh `⚠️ AUTO-LINT:` ke saath tool result me joda jata hai `agent/tools.py:387` — model turant fix kar sake.
*   **Checkpoint undo** — Git hard reset `agent/checkpoint.py:121` `reset --hard HEAD~1` + `clean -fd`, history `agent/checkpoint.py:147` `get_history()`. `/undo` `cli.py:324` se ek command rollback.
*   **Rate limiting** — `agent/ratelimit.py` + `agent/llm.py:192` `with_retries` / `with_retries_stream` exponential backoff, `agent/config.py:55` `rpm/min_interval/max_retries`.

### 5. Evals (LLM-as-Judge)
Har final answer auto-evaluate hota hai:

*   **Dimensions** — `faithfulness, relevance, completeness, groundedness` `agent/eval.py:39` 0.0–1.0, prompt `agent/eval.py:25` `EVAL_PROMPT_TEMPLATE` me query + RAG chunks + tools + response bhejta hai.
*   **Scoring** — `ResponseEvaluator.evaluate()` `agent/eval.py:97` `EVAL_MODEL` `agent/eval.py:23` (default Gemini) `temperature=0.1` `agent/eval.py:152` se stable scoring, JSON parse `agent/eval.py:162` karke `EvaluationResult` `agent/eval.py:52` banata hai. `overall_score` avg `agent/eval.py:64`, `quality_level` Excellent/Good/Fair/Poor `agent/eval.py:68`.
*   **Where used** — `agent/core.py:226` `run()` + `agent/core.py:301` `run_stream()` ke end me `evaluator.evaluate()` + `record_evaluation()` `agent/eval_history.py` → `eval_history.json`. CLI me `cli.py:359` `/stats` `agent/eval.py:185` `format_evaluation` table, `cli.py:423` `agentic eval` se history dekho, `--clear` se reset.

---

## Tech Stack

| Layer | Tech |
|---|---|
| LLM | `google-genai` (Gemini 2.0 Flash), Groq API (`httpx` + `urllib`), Ollama local (`qwen2.5:7b` via `http://localhost:11434`) |
| RAG | `chromadb`, `sentence-transformers`, `tree-sitter` (+ python/js/java/go/rust) |
| CLI | `click`, `rich` (tables, diffs, spinners) |
| Sandbox | `docker` (optional, auto-fallback to subprocess) |
| Config | `tomllib`, `python-dotenv` |
| Tests | `pytest` (58 passed), `ruff` |

---

## Install

The easiest way is the install script:

```bash
curl -fsSL https://raw.githubusercontent.com/Saksham-Khanna/terminal-assistant/main/install | bash
# verify
agentic --version
```

Other methods:

**Using pipx (recommended, isolated):**
```bash
pipx install git+https://github.com/Saksham-Khanna/terminal-assistant.git
# specific version
pipx install git+https://github.com/Saksham-Khanna/terminal-assistant.git@v0.1.0
```

**Using pip:**
```bash
pip install git+https://github.com/Saksham-Khanna/terminal-assistant.git
# after PyPI publish:
pip install helix
```

**Using npm (VS Code extension companion - optional):**
```bash
npm install -g helix-terminal-ai  # if npm wrapper published
```

**Using Homebrew (macOS/Linux - after tap publish):**
```bash
brew tap Saksham-Khanna/tap
brew install helix
```

**Using Docker:**
```bash
docker run -it --rm -v $(pwd):/workspace ghcr.io/saksham-khanna/helix chat
# or build locally
docker build -t helix .
docker run -it helix agentic chat
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/Saksham-Khanna/terminal-assistant/main/install.ps1 | iex
# or with pip
pip install git+https://github.com/Saksham-Khanna/terminal-assistant.git
```

> Installer auto-detects `python3`/`pipx`/`pip`, installs to `~/.local/bin`, and adds to `PATH` in `~/.bashrc`/`~/.zshrc`. Use `--no-modify-path` to skip.

**Install a specific version:**
```bash
curl -fsSL https://raw.githubusercontent.com/Saksham-Khanna/terminal-assistant/main/install | bash -s -- --version 0.1.0
VERSION=0.1.0 curl -fsSL https://raw.githubusercontent.com/Saksham-Khanna/terminal-assistant/main/install | bash
```

### Setup (after install)

```bash
cp .env.example .env
# .env me GEMINI_API_KEY / GROQ_API_KEY / ya Ollama (local, no key) dalo
# Free Gemini key: https://aistudio.google.com/apikey
# Free Groq key: https://console.groq.com
# Ollama: ollama pull qwen2.5:7b && MODEL_PROVIDER=ollama

agentic setup     # provider + API key wizard (also creates agentic.toml)
agentic init      # sessions + .env scaffold (workspace legacy)
```

Dev / local editable install:
```bash
python -m venv venv
# Windows: venv\Scripts\activate | Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

---

## Usage

```bash
# 1. Index project for semantic search (first time / after big changes)
python cli.py index
# or
agentic index

# 2. Interactive chat (read-only by default — project root explore)
python cli.py chat
python cli.py chat --session my-feature
python cli.py chat --continue

# 3. Single task
python cli.py run "Explain how agent loop works in agent/core.py"

# 4. Helpers
python cli.py sessions   # list saved sessions
python cli.py undo       # undo last change
python cli.py diff       # show git diff
```

### Slash Commands (inside `chat`)

| Command | Kaam |
|---|---|
| `/help` | help menu |
| `/save [name]` | session save |
| `/load <id>` | session load |
| `/sessions` | list sessions |
| `/undo` | last edit rollback |
| `/diff` | git diff dekho |
| `/history` | checkpoint history |
| `/reset` | conversation clear |
| `/model [gemini\|groq]` | provider switch |
| `/stats` | token/cost stats |
| `exit` | quit (auto-save) |

---

## Why No Framework?

Intentionally `LangChain / AutoGen` nahi use kiya — taaki har piece (loop, tool dispatch, retrieval, session) visible rahe. Portfolio ke liye yehi point hai: library import karna nahi, mechanics samajhna.

---

## Roadmap

- [x] Diff/patch editing (`edit_file` + unified diffs)
- [x] AST-aware chunking (Tree-sitter)
- [x] Conversation summarization (context budget)
- [x] Session persistence (`.sessions/`)
- [x] Git checkpointing & `/undo` rollback
- [x] Fast regex search (`grep_search`), `read_file_range`, `glob` search
- [x] Auto-lint / syntax validation loop
- [x] Docker sandbox for `run_shell_command`
- [x] Rich terminal UI (colored diffs, tables, spinners)
- [x] Cost/token tracking
- [ ] Hybrid Search (BM25 + Vector RRF)
- [ ] Multi-Agent Planner-Worker
- [ ] Multi-language AST chunking (JS/TS, Go, Rust, Java — partial done)

---

## Resume Bullet (copy-paste)

> **Helix — Terminal Coding Agent (like Claude Code)** — Built LLM agent loop from scratch without frameworks: tool-calling with 10 tools, streaming, AST-aware RAG (Chroma + sentence-transformers + Tree-sitter), session persistence & git checkpoint undo, Docker-sandboxed execution, guardrails + LLM-as-judge evals (faithfulness/relevance/completeness/groundedness). Python, Gemini/Groq/Ollama (qwen2.5:7b local), 58 tests.

---

## License

MIT
