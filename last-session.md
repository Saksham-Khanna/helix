# Last Session — 12 Sept 2026 Night

## Current State (Ready for next session)

**Project:** `Helix` (renamed from agentic-ide `pyproject.toml:6` `helix`, `README.md:1` `# Helix`)
- Terminal coding agent like Claude Code — `agent/core.py:189` loop, `agent/tools.py:42` 10 tools, `rag/` 277 chunks, `agent/checkpoint.py:56` git shadow.
- `AGENT_WORKSPACE=.` `AGENT_READ_ONLY=true` `.env:14` — project root read-only (safe explore), `is_read_only` guard `agent/tools.py:376`.
- Provider: `MODEL_PROVIDER=gemini` `GEMINI_MODEL=gemini-3.5-flash` `.env:4` primary (1M ctx, stable). Groq `openai/gpt-oss-20b` `.env:6` fallback but TPM 8000 tight (~7.5k prompt) `model_change.md:12` — switch to gemini for explore.
- `model_change.md:1` documents 5 options (Gemini stay 0d / Groq trim / HF / Ollama / OpenAI). Ollama next.
- Tests `58 passed` `python -m pytest -q`.

**Web / VS Code:**
- `webapp/server.py:148` restored (FastAPI, `GET /api/health:101`, `GET /api/files:148`, `GET /api/files/read:153`, `POST /api/files/write:165` with read_only guard, `WebSocket /ws/chat:200` with `friendly_error`), `cli.py:444` `web` command.
- `vscode-extension/helix-0.1.0.vsix` 11.17 MB — Antigravity Opus UI polish done:
  - `package.json:23` `viewsContainers.title Agentic IDE -> Helix`, commands `Helix:`, config `Helix`
  - `App.tsx:54` tabs Chat/Files/Diff clean icons (no emojis), `MessageBubble.tsx:12` `Hanken Grotesk` font, `StatusBar.tsx:48` `Connected` text removed -> green dot only `index.css:560`, `SessionPicker.tsx:26` overlap fix (mutual exclusive + outside click), `ChatPanel.tsx:92` done/error robust clear `isStreaming=false` (blinker stops), `index.css:168` toolbar `position:relative`.
- Backend on `http://localhost:8000` health `{"status":"ok","provider":"gemini"}` OK, `GET /api/sessions` `agent/session.py:150` works (`.sessions/`), `GET /api/diff` works.

**Keys:** `.env:2` `GEMINI_API_KEY=AQ.Ab8R...` + `GROQ_API_KEY=gsk_3Gzk...` on disk, `.gitignore:1` safe but exposed in screenshots — rotate pending.

**RAG:** `python cli.py index` -> 277 chunks indexed, `rag/indexer.py:20` SKIP_DIRS expanded.

## Next Session — New Model via Ollama (User choice)

**User will use `qwen2.5:7b-instruct` (recommended for 16GB RAM) instead of Groq/Gemini.**
- Pull: `ollama pull qwen2.5:7b-instruct` (also `gemma3:4b` light 3.5GB alternative tried but qwen better for `agent/tools.py:42` tool-calling). `ollama serve` must run.
- Code to add: `agent/llm.py:188` `_call_ollama()` via `http://localhost:11434/api/chat` (httpx/urllib, UA header), `agent/config.py:69` `ollama` section (`ollama_model`, `ollama_host`), `.env.example:11` + `.env:4` `MODEL_PROVIDER=ollama OLLAMA_MODEL=qwen2.5:7b-instruct`.
- Files to touch `model_change.md:50`: `agent/llm.py:26,59,188` + `agent/config.py:69,192` + `webapp/server.py:101` health expose, `tests/test_llm.py` mock.

**Pending (do next session):**
1. Wire Ollama provider (half-day) + test `ollama run qwen2.5:7b-instruct "list_dir"` via `Agent(MODEL_PROVIDER=ollama).run("say hi")`
2. `assets/demo.gif` 20s `python cli.py chat` `read_file -> edit_file -> pytest` for `README.md:16` (ScreenToGif / terminalizer)
3. Rotate keys `https://aistudio.google.com/apikey` + `https://console.groq.com/keys` -> update `.env:2,5`
4. `git add` unstaged + `git commit` + `git push` (8 files + vsix ignored)
5. Rebuild `vscode-extension` `npm run build` + `vsce package` already 11.17 MB, reinstall via `Install from VSIX` (direct overwrite, no uninstall needed)

## Quick Switch
```bash
# Gemini (current stable)
# .env: MODEL_PROVIDER=gemini  LLM_RATE_RPM=5  LLM_MIN_INTERVAL=2

# Ollama local (next session after wiring)
# ollama pull qwen2.5:7b-instruct
# .env: MODEL_PROVIDER=ollama  OLLAMA_MODEL=qwen2.5:7b-instruct
```
