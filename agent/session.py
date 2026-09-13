"""
Session persistence manager.

Saves and restores conversation history and state across CLI runs.
Sessions are stored as JSON files inside the `.sessions/` directory.
"""

import json
import os
import re
import time
from typing import Optional

from google.genai import types

from agent.config import get_config

SESSIONS_DIR = os.path.abspath(
    get_config().session_dir
)


def _slugify(text: str) -> str:
    """Create a clean filename slug from a string."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:40]


class SessionManager:
    def __init__(self, sessions_dir: Optional[str] = None):
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        os.makedirs(self.sessions_dir, exist_ok=True)

    def _get_session_path(self, session_id: str) -> str:
        # Strip .json if already passed
        if session_id.endswith(".json"):
            session_id = session_id[:-5]
        clean_id = _slugify(session_id) or "session"
        return os.path.join(self.sessions_dir, f"{clean_id}.json")

    def save(
        self,
        agent,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        """
        Save the agent's conversation history to a JSON session file.
        Returns the assigned session_id.
        """
        # Determine or generate session ID
        if not session_id:
            if hasattr(agent, "session_id") and agent.session_id:
                session_id = agent.session_id
            else:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                # Pick a title snippet if available
                snippet = ""
                if hasattr(agent, "initial_query") and agent.initial_query:
                    snippet = f"_{_slugify(agent.initial_query)[:20]}"
                session_id = f"session_{timestamp}{snippet}"

        session_path = self._get_session_path(session_id)

        # Derive title if not provided
        if not title:
            if hasattr(agent, "initial_query") and agent.initial_query:
                title = agent.initial_query[:80]
            else:
                title = session_id

        # Serialize Gemini contents
        serialized_contents = []
        for c in agent.contents:
            if isinstance(c, types.Content):
                serialized_contents.append(c.model_dump(mode="json"))
            elif isinstance(c, dict):
                serialized_contents.append(c)

        # Count turns
        if agent.provider in ("groq", "ollama"):
            turn_count = len(getattr(agent, "groq_messages", []))
        else:
            turn_count = len(agent.contents)

        # Read existing created_at if updating
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if os.path.exists(session_path):
            try:
                with open(session_path, "r", encoding="utf-8") as f:
                    prev_data = json.load(f)
                    created_at = prev_data.get("created_at", created_at)
            except Exception:
                pass

        session_data = {
            "session_id": session_id,
            "title": title,
            "provider": agent.provider,
            "created_at": created_at,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "turn_count": turn_count,
            "gemini_contents": serialized_contents,
            "groq_messages": getattr(agent, "groq_messages", []),
        }

        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

        agent.session_id = session_id
        return session_id

    def load(self, agent, session_id: str) -> bool:
        """
        Load a session from disk and restore it into the agent instance.
        """
        session_path = self._get_session_path(session_id)
        if not os.path.exists(session_path):
            # Try searching by matching prefix or filename directly
            all_sessions = self.list_sessions()
            matched = [s for s in all_sessions if s["session_id"] == session_id or s["session_id"].startswith(session_id)]
            if matched:
                session_path = self._get_session_path(matched[0]["session_id"])
            else:
                return False

        try:
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading session file {session_path}: {e}")
            return False

        agent.session_id = data.get("session_id", session_id)
        agent.provider = data.get("provider", agent.provider)
        agent.groq_messages = data.get("groq_messages", [])

        # Restore Gemini contents
        raw_contents = data.get("gemini_contents", [])
        restored_contents = []
        for item in raw_contents:
            try:
                restored_contents.append(types.Content.model_validate(item))
            except Exception as e:
                # If validation fails on partial data, keep item or skip
                pass
        agent.contents = restored_contents

        return True

    def list_sessions(self) -> list[dict]:
        """
        List all saved sessions sorted by most recently updated.
        """
        if not os.path.exists(self.sessions_dir):
            return []

        sessions = []
        for filename in os.listdir(self.sessions_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.sessions_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", filename[:-5]),
                    "title": data.get("title", "(untitled)"),
                    "provider": data.get("provider", "unknown"),
                    "turn_count": data.get("turn_count", 0),
                    "updated_at": data.get("updated_at", ""),
                    "created_at": data.get("created_at", ""),
                })
            except Exception:
                continue

        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return sessions

    def get_latest_session_id(self) -> Optional[str]:
        """Return the session_id of the most recently updated session."""
        sessions = self.list_sessions()
        if sessions:
            return sessions[0]["session_id"]
        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file from disk."""
        session_path = self._get_session_path(session_id)
        if os.path.exists(session_path):
            try:
                os.remove(session_path)
                return True
            except OSError:
                return False
        return False
