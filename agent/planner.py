"""
Planner-Worker: generate a plan before destructive edits.

The planner uses only read/search tools to explore the codebase,
then proposes a concise plan (steps, files, risk) which requires
human approval before the worker (normal agent loop) executes it.
"""

import json
from typing import Optional

from agent.tools import TOOL_SCHEMAS

# Read-only tools allowed during planning
READ_TOOLS = [t for t in TOOL_SCHEMAS if t["name"] in (
    "read_file", "read_file_range", "list_dir", "grep_search",
    "find_files_by_glob", "search_codebase"
)]

PLANNER_SYSTEM = """You are a planning assistant. Your job is to propose a minimal, safe plan to accomplish the user's task.

Rules:
- Use ONLY read/search tools to investigate — do NOT propose writes/edits yet.
- After investigating, output a JSON plan with this exact shape:
  {
    "goal": "one-sentence goal",
    "steps": [{"id": 1, "action": "what to do", "files": ["path"], "tool": "read_file|edit_file|write_file|run_shell_command|..."}],
    "files_to_modify": ["path1", "path2"],
    "risk": "low|medium|high",
    "verification": "how to verify (e.g. pytest)"
  }
- Keep steps 3-7, each step one tool call. Prefer edit_file over write_file.
- If no file changes needed, set files_to_modify=[] and risk=low.
- Do NOT call write_file/edit_file/run_shell_command yet — only propose.
- After you have enough context, return the JSON as plain text (no tool calls).
"""

def is_planner_enabled() -> bool:
    import os
    return (os.environ.get("HELIX_PLANNER") or os.environ.get("AGENT_PLANNER") or "").lower() == "true"

def parse_plan(text: str) -> Optional[dict]:
    """Try to extract JSON plan from model text."""
    if not text:
        return None
    # Find JSON block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    snippet = text[start:end+1]
    try:
        data = json.loads(snippet)
        if "steps" in data and "files_to_modify" in data:
            return data
    except Exception:
        pass
    return None

def format_plan_markdown(plan: dict) -> str:
    lines = []
    lines.append(f"**Goal:** {plan.get('goal','')}")
    lines.append(f"**Risk:** {plan.get('risk','')}")
    lines.append("")
    lines.append("| # | Action | Files | Tool |")
    lines.append("|---|--------|-------|------|")
    for s in plan.get("steps", []):
        files = ", ".join(s.get("files", []))
        lines.append(f"| {s.get('id','')} | {s.get('action','')} | {files} | {s.get('tool','')} |")
    lines.append("")
    if plan.get("files_to_modify"):
        lines.append(f"**Files to modify:** {', '.join(plan['files_to_modify'])}")
    if plan.get("verification"):
        lines.append(f"**Verify:** {plan['verification']}")
    return "\n".join(lines)
