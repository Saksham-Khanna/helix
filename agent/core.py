"""
The agent loop.

This is the whole "brain" of the system: send messages -> get a response ->
if the model asked to use a tool, run it and feed the result back -> repeat
until the model replies with plain text (no more tool calls) or we hit the
safety cap on iterations.

Gemini's conversation format: a list of `types.Content` objects, each with
a role ("user" or "model") and a list of `Part`s. A tool call from the model
shows up as a function_call Part inside a "model" turn; you answer it with a
function_response Part inside the next "user" turn. Conceptually identical
to Claude's tool_use/tool_result — just different object names.
"""

import concurrent.futures
import json
import time
from typing import Generator, Optional

from google.genai import types

from agent.llm import LLMClient
from agent.tools import TOOL_SCHEMAS, execute_tool
from agent.config import get_config
from agent.planner import READ_TOOLS, PLANNER_SYSTEM, parse_plan, format_plan_markdown, is_planner_enabled
from agent.summarizer import (
    should_summarize_gemini,
    should_summarize_groq,
    summarize_gemini,
    summarize_groq,
)
from agent.eval import ResponseEvaluator, EvaluationResult, format_evaluation
from agent.eval_history import record_evaluation
from agent.session import SessionManager
from agent.checkpoint import CheckpointManager
from agent.ui import tool_call_line, print_spinner, console
from agent.cost import (
    SessionUsage,
    estimate_gemini_tokens,
    estimate_groq_tokens,
)

SYSTEM_PROMPT = """You are an autonomous coding agent operating inside a sandboxed workspace.

You have tools to read/write files, list directories, run shell commands, and
semantically search an indexed codebase. Use them to accomplish the user's task.

Guidelines:
- Investigate before acting: read relevant files or search the codebase before writing code.
- Make minimal, targeted changes. For small changes to an existing file, prefer
  the edit_file tool (surgical, reviewable diff) over write_file. Only use
  write_file when creating a new file or rewriting the whole file.
- After making a change, verify it (e.g. run tests or the affected script) when possible.
- When you're done, reply with a plain-text summary of what you did. Do not call
  any more tools once the task is complete.
- Note: Long conversations may be compressed automatically. Previous messages might
  appear as a summary. Always re-read files if you need fresh context rather than
  assuming you remember their contents from earlier.
"""

MAX_ITERATIONS = 25


class Agent:
    def __init__(self, session_id: Optional[str] = None, enable_evaluation: bool | None = None):
        self.llm = LLMClient()
        self.provider = get_config().provider
        self.contents: list[types.Content] = []
        self.groq_messages: list = []
        self.system = SYSTEM_PROMPT

        # Session & Checkpointing
        self.session_mgr = SessionManager()
        self.checkpoint_mgr = CheckpointManager()
        self.session_id = session_id
        self.initial_query = ""

        if session_id:
            self.load_session(session_id)

        # Evaluation tracking - respect ENABLE_EVALUATION env
        import os
        if enable_evaluation is None:
            enable_evaluation = os.environ.get("ENABLE_EVALUATION", "true").lower() == "true"
        self.enable_evaluation = enable_evaluation
        self.evaluator = ResponseEvaluator() if enable_evaluation else None
        self.context_chunks_used: list[str] = []
        self.tools_called: list[dict] = []

        # Usage / cost tracking
        self.usage = SessionUsage()
        self._iteration = 0

        # Observers get notified on tool calls (for external UI)
        self.tool_observers: list = []
        # Approval flow for destructive tools (web UI)
        self.require_approval = get_config().require_approval
        self.approval_callback = None  # set by webapp to (name, args) -> bool
        # Planner-Worker
        self.planner_enabled = is_planner_enabled()
        self.plan_approval_callback = None  # set by webapp to (plan: dict) -> bool

    def _is_approval_required(self, tool_name: str, args: dict) -> bool:
        if not self.require_approval:
            return False
        # Only destructive tools need approval
        if tool_name not in ("write_file", "edit_file", "run_shell_command", "undo_last_change"):
            return False
        # Safe shell commands auto-allowed even with approval on
        if tool_name == "run_shell_command":
            cmd = args.get("command", "")
            from agent.tools import SAFE_COMMAND_PREFIXES
            if cmd.strip().startswith(SAFE_COMMAND_PREFIXES):
                return False
        return True

    def _request_approval(self, tool_name: str, args: dict) -> bool:
        if not self._is_approval_required(tool_name, args):
            return True
        if self.approval_callback:
            try:
                return bool(self.approval_callback(tool_name, args))
            except Exception:
                return False
        # CLI fallback: ask via input
        try:
            ans = input(f"\n  Agent wants to run {tool_name} {args}\n  Approve? [y/N] ").strip().lower()
            return ans == "y"
        except Exception:
            return False

    def _request_plan_approval(self, plan: Optional[dict], markdown: str) -> bool:
        if not self.planner_enabled:
            return True
        if self.plan_approval_callback:
            try:
                return bool(self.plan_approval_callback(plan, markdown))
            except Exception:
                return False
        # CLI fallback: print plan and ask
        try:
            print("\n" + "="*60)
            print("📋 PLAN PROPOSAL")
            print("="*60)
            print(markdown)
            print("="*60)
            ans = input("Approve this plan? [y/N] ").strip().lower()
            return ans == "y"
        except Exception:
            return False

    def _append_user(self, text: str):
        if not self.initial_query:
            self.initial_query = text
        if self.provider in ("groq", "ollama"):
            self.groq_messages.append({"role": "user", "content": text})
        else:
            self.contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text=text)])
            )

    def _append_model(self, text: str):
        if self.provider in ("groq", "ollama"):
            self.groq_messages.append({"role": "assistant", "content": text})
        else:
            self.contents.append(
                types.Content(role="model", parts=[types.Part.from_text(text=text)])
            )

    def save_session(self, session_id: Optional[str] = None, title: Optional[str] = None) -> str:
        """Persist current conversation history to disk."""
        return self.session_mgr.save(self, session_id=session_id, title=title)

    def load_session(self, session_id: str) -> bool:
        """Load conversation history from disk."""
        return self.session_mgr.load(self, session_id)

    def undo_last_checkpoint(self) -> tuple[bool, str]:
        """Rollback the workspace to the previous commit/checkpoint."""
        return self.checkpoint_mgr.undo_last_checkpoint()

    def get_workspace_diff(self) -> str:
        """Get git diff of current workspace changes."""
        return self.checkpoint_mgr.get_workspace_diff()

    def get_checkpoint_history(self, limit: int = 5) -> list[dict]:
        """Get list of recent checkpoints."""
        return self.checkpoint_mgr.get_history(limit)

    def reset(self):
        """Clear conversation history and start fresh."""
        self.contents = []
        self.groq_messages = []
        self.ollama_messages = [] if hasattr(self, 'ollama_messages') else []
        self.context_chunks_used = []
        self.tools_called = []
        self.initial_query = ""
        self.usage = SessionUsage()
        self._iteration = 0

    def _record_usage(self, response) -> None:
        """Record token usage for the latest LLM call."""
        if self.provider in ("groq", "ollama"):
            prompt_tokens, output_tokens = estimate_groq_tokens(response)
        else:
            prompt_tokens, output_tokens = estimate_gemini_tokens(response)

        if self.provider == "ollama":
            model = get_config().ollama_model
        elif self.provider == "groq":
            model = get_config().groq_model
        else:
            model = get_config().gemini_model

        if prompt_tokens or output_tokens:
            self.usage.record_call(
                provider=self.provider,
                model=model,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                iteration=self._iteration,
            )

    def get_usage_summary(self) -> str:
        """Return a human-readable usage summary for the current session."""
        from agent.cost import format_usage
        self.usage.tool_calls = len(self.tools_called)
        self.usage.end_time = time.time()
        return format_usage(self.usage)


    def _maybe_summarize(self):
        """Compress old messages if context is getting too long."""
        if self.provider in ("groq", "ollama"):
            if should_summarize_groq(self.groq_messages):
                self.groq_messages = summarize_groq(
                    self.llm.client if hasattr(self.llm, "client") else None,
                    self.groq_messages,
                    self.system,
                )
        else:
            if should_summarize_gemini(self.contents):
                self.contents = summarize_gemini(
                    self.llm.client,
                    self.contents,
                    self.system,
                )

    def _generate_plan(self, user_task: str) -> tuple[Optional[dict], str]:
        """Run a read-only planner loop to produce a JSON plan. Returns (plan, markdown)."""
        # Use a separate history so we don't pollute main conversation
        # For simplicity, reuse Agent's llm but with PLANNER_SYSTEM and READ_TOOLS
        # Keep it to 5 iterations of read/search only
        from google.genai import types as _types
        # Build planner messages
        planner_contents = []
        planner_groq = []
        is_openai = self.provider in ("groq", "ollama")
        # Seed user task
        if is_openai:
            planner_groq.append({"role": "user", "content": user_task})
        else:
            planner_contents.append(_types.Content(role="user", parts=[_types.Part.from_text(text=user_task)]))

        plan_text = ""
        for _ in range(5):
            # Call LLM with planner system and read-only tools
            if self.provider == "groq":
                self.llm.set_groq_messages(planner_groq)
            elif self.provider == "ollama":
                if hasattr(self.llm, "set_ollama_messages"):
                    self.llm.set_ollama_messages(planner_groq)
                else:
                    self.llm.set_groq_messages(planner_groq)
            try:
                response = self.llm.call(
                    contents=planner_contents if not is_openai else [],
                    system=PLANNER_SYSTEM,
                    tools=READ_TOOLS,
                )
            except Exception as e:
                plan_text = f"Planner error: {e}"
                break

            # Parse response
            if is_openai:
                # Groq/Ollama shape
                msg = response.get("choices", [{}])[0].get("message", {})
                text = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []
                # If no tool calls, this is the plan JSON
                if not tool_calls:
                    plan_text = text
                    break
                # Execute read tools only
                # Append assistant msg
                planner_groq.append({"role": "assistant", "content": text, "tool_calls": [{"id": tc["id"], "type": "function", "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}} for tc in tool_calls]})
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except Exception:
                        args = {}
                    if name not in ("read_file", "read_file_range", "list_dir", "grep_search", "find_files_by_glob", "search_codebase"):
                        result = f"Tool '{name}' not allowed in planner — use only read/search tools."
                    else:
                        result = execute_tool(name, args)
                    planner_groq.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                    # Also track context
                    if name == "search_codebase" and not result.startswith("Error"):
                        self.context_chunks_used.append(result[:500])
            else:
                # Gemini
                cand = response.candidates[0]
                content = cand.content
                fcs = [p.function_call for p in content.parts if getattr(p, "function_call", None)]
                if not fcs:
                    # Plain text => plan
                    plan_text = "\n".join([p.text for p in content.parts if getattr(p, "text", None)])
                    break
                planner_contents.append(content)
                parts = []
                for fc in fcs:
                    name = fc.name
                    args = dict(fc.args)
                    if name not in ("read_file", "read_file_range", "list_dir", "grep_search", "find_files_by_glob", "search_codebase"):
                        result = f"Tool '{name}' not allowed in planner — use only read/search tools."
                    else:
                        result = execute_tool(name, args)
                        if name == "search_codebase" and not result.startswith("Error"):
                            self.context_chunks_used.append(result[:500])
                    parts.append(_types.Part.from_function_response(name=name, response={"result": result}))
                planner_contents.append(_types.Content(role="user", parts=parts))

        plan = parse_plan(plan_text or "") if plan_text else None
        if plan:
            md = format_plan_markdown(plan)
            return plan, md
        # Fallback: treat whole text as plan markdown
        return None, plan_text or "No plan generated."

    def run(self, user_task: str) -> tuple[str, Optional[EvaluationResult]]:
        """
        Run agent with evaluation.

        Returns:
            Tuple of (response_text, evaluation_result)
        """
        self._append_user(user_task)
        self.context_chunks_used = []
        self.tools_called = []

        # Planner-Worker: generate plan and ask approval before any edits
        if self.planner_enabled:
            plan, md = self._generate_plan(user_task)
            if not self._request_plan_approval(plan, md):
                return "Plan denied by user — no changes made.", None
            self._append_user(f"Approved plan to execute:\n{md}\n\nProceed step by step, using edit_file/write_file/run_shell_command as needed.")

        for iteration in range(1, MAX_ITERATIONS + 1):
            self._iteration = iteration
            self._maybe_summarize()

            if self.provider == "groq":
                self.llm.set_groq_messages(self.groq_messages)
            elif self.provider == "ollama":
                if hasattr(self.llm, "set_ollama_messages"):
                    self.llm.set_ollama_messages(self.groq_messages)
                else:
                    self.llm.set_groq_messages(self.groq_messages)
            with print_spinner("Agent thinking..."):
                response = self.llm.call(
                    contents=self.contents,
                    system=self.system,
                    tools=TOOL_SCHEMAS,
                )

            self._record_usage(response)

            if self.provider in ("groq", "ollama"):
                result = self._run_groq_iteration(response)
            else:
                result = self._run_gemini_iteration(response)

            if result is not None:
                # Auto-save session if session_id is active
                if self.session_id:
                    self.save_session(self.session_id)
                # Evaluate the final response
                eval_result = None
                if self.evaluator:
                    eval_result = self.evaluator.evaluate(
                        query=user_task,
                        response=result,
                        context_chunks=self.context_chunks_used,
                        tools_called=self.tools_called,
                    )
                    if eval_result:
                        record_evaluation(eval_result)
                return result, eval_result

        return "Stopped: hit the max iteration limit without finishing the task.", None

    def run_stream(self, user_task: str) -> Generator[str | EvaluationResult, None, None]:
        """
        Stream agent response. Yields text chunks as they arrive.
        Final yield is the EvaluationResult (if evaluation enabled).
        """
        self._append_user(user_task)
        self.context_chunks_used = []
        self.tools_called = []

        # Planner-Worker for streaming: generate plan, yield it, await approval
        if self.planner_enabled:
            plan, md = self._generate_plan(user_task)
            yield f"📋 **PLAN PROPOSAL**\n\n{md}\n\n_Awaiting approval..._\n"
            if not self._request_plan_approval(plan, md):
                yield "Plan denied by user — no changes made."
                return
            self._append_user(f"Approved plan to execute:\n{md}\n\nProceed step by step.")
            yield f"✅ Plan approved — executing...\n\n"

        for iteration in range(1, MAX_ITERATIONS + 1):
            self._maybe_summarize()

            if self.provider == "groq":
                self.llm.set_groq_messages(self.groq_messages)
            elif self.provider == "ollama":
                if hasattr(self.llm, "set_ollama_messages"):
                    self.llm.set_ollama_messages(self.groq_messages)
                else:
                    self.llm.set_groq_messages(self.groq_messages)

            # Use streaming (Groq/Ollama fall back to non-stream on error)
            accumulated_text = ""
            tool_calls = []

            try:
                for chunk in self.llm.stream(
                    contents=self.contents,
                    system=self.system,
                    tools=TOOL_SCHEMAS,
                ):
                    if chunk["type"] == "text":
                        accumulated_text += chunk["data"]
                        yield chunk["data"]
                    elif chunk["type"] == "tool_call":
                        tool_calls.append(chunk["data"])
            except Exception as e:
                if self.provider in ("groq", "ollama"):
                    # Fallback to non-streaming Groq/Ollama call
                    try:
                        response = self.llm.call(contents=self.contents, system=self.system, tools=TOOL_SCHEMAS)
                        result = self._run_groq_iteration(response)
                        if result is not None:
                            accumulated_text = result
                            if accumulated_text:
                                yield accumulated_text
                            tool_calls = []
                        else:
                            # Tool calls already handled, continue loop
                            continue
                        # Handle final eval/save for fallback path
                        if not tool_calls and accumulated_text:
                            if self.session_id:
                                self.save_session(self.session_id)
                            if self.evaluator and accumulated_text:
                                try:
                                    eval_result = self.evaluator.evaluate(query=user_task, response=accumulated_text, context_chunks=self.context_chunks_used, tools_called=self.tools_called)
                                    if eval_result:
                                        from agent.eval_history import record_evaluation
                                        record_evaluation(eval_result)
                                        yield eval_result
                                except Exception:
                                    pass
                            return
                        elif not tool_calls and not accumulated_text:
                            continue
                    except Exception as e2:
                        from agent.errors import friendly_error
                        hint = friendly_error(e2)
                        # Show friendly hint, not raw JSON
                        yield f"\n\n**Rate limit / API error:** {hint}\n\n_Tip: switch to `MODEL_PROVIDER=gemini` in `.env` for project exploration (1M context), Groq TPM 8000 is too small for full project prompt (~7.5k). Retry in 20-30s._"
                        return
                else:
                    raise

            # Record usage (streaming - rough char-based estimate)
            from agent.cost import estimate_tokens_char_fallback
            from agent.cost import PRICING
            pricing = PRICING.get(self.provider, PRICING["gemini"])
            prompt_text = "".join(
                p.text for c in self.contents for p in c.parts if getattr(p, "text", None)
            ) if self.provider not in ("groq", "ollama") else ""
            if self.provider in ("groq", "ollama"):
                prompt_tokens = estimate_tokens_char_fallback(
                    "".join(m.get("content", "") for m in self.groq_messages if isinstance(m.get("content"), str))
                )
            else:
                prompt_tokens = estimate_tokens_char_fallback(prompt_text)
            output_tokens = estimate_tokens_char_fallback(accumulated_text)
            if self.provider == "ollama":
                model_name = get_config().ollama_model
            elif self.provider == "groq":
                model_name = get_config().groq_model
            else:
                model_name = get_config().gemini_model
            self.usage.record_call(
                provider=self.provider,
                model=model_name,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                iteration=iteration,
            )

            # If no tool calls, we're done
            if not tool_calls:
                if not accumulated_text:
                    yield "\n[Warning] Model returned empty response (no text, no tool calls). Check quota/rate-limit."
                if accumulated_text:
                    self._append_model(accumulated_text)

                # Auto-save session if session_id is active
                if self.session_id:
                    self.save_session(self.session_id)

                # Evaluate final response
                if self.evaluator and accumulated_text:
                    eval_result = self.evaluator.evaluate(
                        query=user_task,
                        response=accumulated_text,
                        context_chunks=self.context_chunks_used,
                        tools_called=self.tools_called,
                    )
                    if eval_result:
                        record_evaluation(eval_result)
                        yield eval_result
                return

            # Handle tool calls
            if accumulated_text:
                self._append_model(accumulated_text)

            # Execute tools
            response_parts = []
            for tc in tool_calls:
                name = tc["name"]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                print(f"\n")
                tool_call_line(name, args)
                self.tools_called.append({"name": name, "args": args})
                for obs in self.tool_observers:
                    try:
                        obs(name, dict(args))
                    except Exception:
                        pass
                if self._is_approval_required(name, args) and not self._request_approval(name, args):
                    result_text = f"Tool '{name}' blocked by user — approval denied."
                else:
                    result_text = execute_tool(name, args)

                # Track RAG context if search_codebase was used
                if name == "search_codebase" and result_text and not result_text.startswith("Error"):
                    self.context_chunks_used.append(result_text[:500])  # Store preview

                response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": result_text},
                    )
                )

            if self.provider in ("groq", "ollama"):
                for tc, part in zip(tool_calls, response_parts):
                    self.groq_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": part.function_response.response.get("result", ""),
                    })
            else:
                self.contents.append(types.Content(role="user", parts=response_parts))

        yield "\nStopped: hit the max iteration limit without finishing the task."

    def _run_gemini_iteration(self, response):
        candidate = response.candidates[0]
        model_content = candidate.content
        self.contents.append(model_content)

        function_calls = [
            part.function_call for part in model_content.parts
            if getattr(part, "function_call", None)
        ]

        if not function_calls:
            text_parts = [
                part.text for part in model_content.parts
                if getattr(part, "text", None)
            ]
            return "\n".join(text_parts)

        response_parts = []

        for fc in function_calls:
            tool_call_line(fc.name, dict(fc.args))
            self.tools_called.append({"name": fc.name, "args": dict(fc.args)})

        # Handle approval-gated tools sequentially, others in parallel
        approval_denied = []
        parallel_calls = []
        for fc in function_calls:
            args = dict(fc.args)
            if self._is_approval_required(fc.name, args):
                if not self._request_approval(fc.name, args):
                    approval_denied.append(fc)
                    response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": f"Tool '{fc.name}' blocked by user — approval denied."},
                        )
                    )
                else:
                    parallel_calls.append(fc)
            else:
                parallel_calls.append(fc)

        if parallel_calls:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_fc = {
                    executor.submit(execute_tool, fc.name, dict(fc.args)): fc
                    for fc in parallel_calls
                }
                for future in concurrent.futures.as_completed(future_to_fc):
                    fc = future_to_fc[future]
                    try:
                        result_text = future.result()
                    except Exception as e:
                        result_text = f"Error: {e}"
                    if fc.name == "search_codebase" and not result_text.startswith("Error"):
                        self.context_chunks_used.append(result_text[:500])
                    response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": result_text},
                        )
                    )

        self.contents.append(types.Content(role="user", parts=response_parts))
        return None

    def _run_groq_iteration(self, response):
        message = response.get("choices", [{}])[0].get("message", {})
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        # Build assistant message with tool calls for the conversation history
        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            groq_tool_calls = []
            for tc in tool_calls:
                groq_tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                })
            assistant_msg["tool_calls"] = groq_tool_calls
        self.groq_messages.append(assistant_msg)

        if not tool_calls:
            return content.strip() if content else "(no response)"

        # Execute tools and feed results back (with approval)
        import json
        tool_result_msgs = []
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            tool_call_line(name, args)
            self.tools_called.append({"name": name, "args": args})
            if self._is_approval_required(name, args) and not self._request_approval(name, args):
                result_text = f"Tool '{name}' blocked by user — approval denied."
            else:
                result_text = execute_tool(name, args)
            if name == "search_codebase" and not result_text.startswith("Error"):
                self.context_chunks_used.append(result_text[:500])
            tool_result_msgs.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

        self.groq_messages.extend(tool_result_msgs)

        # Also keep Gemini-style contents in sync for LLMClient
        # (LLMClient's _call_groq reads from self.contents; store messages there too)
        return None
