"""
FastAPI backend for the Agentic IDE web UI.

Serves the static web app and exposes:
  - WebSocket /ws/chat        -> streaming agent conversations
  - GET /api/health           -> server status
  - GET /api/sessions         -> list saved sessions
  - GET /api/diff             -> workspace git diff
  - POST /api/index           -> trigger RAG indexing
  - GET /api/files            -> workspace file tree
  - GET /api/files/read       -> read a file from the workspace

Run with:
    agentic web [--port 8000] [--host 127.0.0.1]
"""

import asyncio
import json
import os
import threading
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

from agent.core import Agent
from agent.session import SessionManager
from agent.checkpoint import CheckpointManager
from agent.tools import WORKSPACE_ROOT
from agent.config import get_config

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Agentic IDE Web", version="0.1.0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_chunk(chunk) -> Optional[dict]:
    """Convert an agent stream chunk into a JSON-serializable message."""
    if isinstance(chunk, str):
        return {"type": "text", "data": chunk}
    # EvaluationResult
    return {"type": "eval", "data": chunk.to_dict()}


def _build_file_tree(root: str) -> list[dict]:
    """Build a nested file tree of the workspace (ignoring heavy dirs)."""
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".sessions", ".pytest_cache", ".chroma", "rag_db"}

    def walk(dirpath: str, rel: str) -> list[dict]:
        entries = []
        try:
            names = sorted(os.listdir(dirpath), key=str.lower)
        except (FileNotFoundError, PermissionError):
            return entries
        for name in names:
            full = os.path.join(dirpath, name)
            rel_path = name if not rel else f"{rel}/{name}"
            if os.path.isdir(full):
                if name in skip_dirs:
                    continue
                entries.append({
                    "name": name,
                    "path": rel_path,
                    "type": "dir",
                    "children": walk(full, rel_path),
                })
            else:
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                entries.append({
                    "name": name,
                    "path": rel_path,
                    "type": "file",
                    "size": size,
                })
        return entries

    return walk(root, "")


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
async def health():
    config = get_config()
    if config.provider == "ollama":
        model = config.ollama_model
    elif config.provider == "groq":
        model = config.groq_model
    else:
        model = config.gemini_model
    return {
        "status": "ok",
        "provider": config.provider,
        "workspace": WORKSPACE_ROOT,
        "model": model,
        "ollama_host": config.ollama_host if config.provider == "ollama" else None,
    }


@app.get("/api/sessions")
async def list_sessions():
    mgr = SessionManager()
    return {"sessions": mgr.list_sessions()}


@app.get("/api/diff")
async def diff():
    mgr = CheckpointManager()
    return {"diff": mgr.get_workspace_diff()}


@app.post("/api/index")
async def index_workspace():
    try:
        from rag.indexer import index_directory
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Indexing unavailable: {e}"})

    result: dict = {}
    def _do_index():
        try:
            count = index_directory(WORKSPACE_ROOT)
            result["count"] = count
            result["error"] = None
        except Exception as e:
            result["count"] = 0
            result["error"] = str(e)

    thread = threading.Thread(target=_do_index, daemon=True)
    thread.start()
    thread.join(timeout=180)
    if result.get("error"):
        return JSONResponse(status_code=500, content={"error": result["error"]})
    return {"count": result.get("count", 0)}


@app.get("/api/files")
async def files():
    return {"root": WORKSPACE_ROOT, "tree": _build_file_tree(WORKSPACE_ROOT)}


@app.get("/api/files/read")
async def read_file(path: str):
    from agent.tools import _resolve
    try:
        full = _resolve(path)
        if not os.path.exists(full) or os.path.isdir(full):
            return JSONResponse(status_code=404, content={"error": f"File not found: {path}"})
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/api/files/write")
async def write_file(payload: dict):
    from agent.tools import _resolve
    from agent.config import get_config
    path = payload.get("path", "")
    content = payload.get("content", "")
    try:
        # Respect AGENT_READ_ONLY guard (same as tool guard)
        cfg = get_config()
        if getattr(cfg, "is_read_only", False):
            return JSONResponse(status_code=403, content={"error": "Write blocked: AGENT_READ_ONLY=true (set to false in .env to allow edits)"})
        full = _resolve(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            from agent.checkpoint import CheckpointManager
            CheckpointManager().commit_if_needed(f"edit {path} via Files tab")
        except Exception:
            pass
        return {"path": path, "ok": True}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# ---------------------------------------------------------------------------
# WebSocket - streaming chat
# ---------------------------------------------------------------------------

def _agent_stream(agent: Agent, message: str, queue: asyncio.Queue):
    """Run the agent in a background thread and push chunks to the queue."""
    def _on_tool(name, args):
        try:
            queue.put_nowait(("tool", {"name": name, "args": args}))
        except Exception:
            pass
    agent.tool_observers.append(_on_tool)
    try:
        for chunk in agent.run_stream(message):
            queue.put_nowait(("chunk", chunk))
    except Exception as e:
        try:
            from agent.errors import friendly_error
            queue.put_nowait(("error", friendly_error(e)))
        except Exception:
            queue.put_nowait(("error", str(e)))
    finally:
        try:
            agent.tool_observers.remove(_on_tool)
        except ValueError:
            pass
        try:
            queue.put_nowait(("usage", agent.get_usage_summary()))
        except Exception:
            queue.put_nowait(("usage", ""))
        queue.put_nowait(("done", None))


@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    agent = Agent(enable_evaluation=None)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                message = data.get("message", "")
                if not message.strip():
                    continue

                await ws.send_json({"type": "status", "data": "thinking"})
                queue: asyncio.Queue = asyncio.Queue()
                thread = threading.Thread(
                    target=_agent_stream,
                    args=(agent, message, queue),
                    daemon=True,
                )
                thread.start()

                while True:
                    kind, payload = await queue.get()
                    if kind == "chunk":
                        msg = _serialize_chunk(payload)
                        if msg:
                            await ws.send_json(msg)
                    elif kind == "tool":
                        await ws.send_json({"type": "tool", "data": payload})
                    elif kind == "error":
                        await ws.send_json({"type": "error", "data": payload})
                    elif kind == "usage":
                        await ws.send_json({"type": "usage", "data": payload})
                    elif kind == "done":
                        await ws.send_json({"type": "done"})
                        break

            elif msg_type == "reset":
                if agent.session_id:
                    try:
                        agent.save_session(agent.session_id)
                    except Exception:
                        pass
                agent.reset()
                await ws.send_json({"type": "status", "data": "reset"})

            elif msg_type == "load_session":
                session_id = data.get("session_id")
                if session_id and agent.load_session(session_id):
                    await ws.send_json({"type": "status", "data": f"loaded:{session_id}"})
                else:
                    await ws.send_json({"type": "error", "data": f"Session '{session_id}' not found"})

            elif msg_type == "save_session":
                name = data.get("name")
                saved_id = agent.save_session(session_id=name if name else None)
                await ws.send_json({"type": "status", "data": f"saved:{saved_id}"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Launch the uvicorn dev server."""
    import uvicorn
    uvicorn.run("webapp.server:app", host=host, port=port, reload=reload, log_level="info")


if __name__ == "__main__":
    run_server()