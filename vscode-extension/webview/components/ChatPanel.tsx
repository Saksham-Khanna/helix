import React, { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, ToolCall, WsIncoming } from "../types";
import { useWebSocket, ConnectionStatus } from "../hooks/useWebSocket";
import { MessageBubble } from "./MessageBubble";
import { StatusBar } from "./StatusBar";
import { SessionPicker } from "./SessionPicker";

interface Props {
  backendUrl: string;
  token: string;
}

let msgCounter = 0;
function nextId(): string {
  return `msg-${Date.now()}-${++msgCounter}`;
}

export const ChatPanel: React.FC<Props> = ({ backendUrl, token }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [usageInfo, setUsageInfo] = useState("");
  const [pendingApproval, setPendingApproval] = useState<{ id: string; tool: string; args: Record<string, any>; preview: string } | null>(null);
  const [pendingPlan, setPendingPlan] = useState<{ id: string; plan: Record<string, any> | null; markdown: string } | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastEval, setLastEval] = useState<Record<string, any> | null>(null);
  const lastUserMsgRef = useRef<string>("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentAgentMsgRef = useRef<string | null>(null);
  const pendingToolCalls = useRef<ToolCall[]>([]);
  const inputHistory = useRef<string[]>([]);
  const historyIndex = useRef<number>(-1);
  const draftInput = useRef<string>("");

  const handleWsMessage = useCallback((msg: WsIncoming) => {
    switch (msg.type) {
      case "status":
        if (msg.data === "thinking") {
          setIsThinking(true);
          // Create a new agent message placeholder
          const agentId = nextId();
          currentAgentMsgRef.current = agentId;
          pendingToolCalls.current = [];
          setMessages((prev) => [
            ...prev,
            { id: agentId, role: "agent", content: "", timestamp: Date.now(), isStreaming: true, toolCalls: [] },
          ]);
        } else if (msg.data === "reset") {
          setMessages([]);
        } else if (msg.data.startsWith("loaded:")) {
          const sid = msg.data.replace("loaded:", "");
          setMessages([
            { id: nextId(), role: "agent", content: `*Session \`${sid}\` loaded.*`, timestamp: Date.now() },
          ]);
        } else if (msg.data.startsWith("saved:")) {
          const sid = msg.data.replace("saved:", "");
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: "agent", content: `*Session saved as \`${sid}\`.*`, timestamp: Date.now() },
          ]);
        }
        break;

      case "text":
        // Append text to current agent message
        if (currentAgentMsgRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, content: m.content + msg.data }
                : m
            )
          );
        }
        break;

      case "tool":
        // Add tool call to current agent message
        if (currentAgentMsgRef.current) {
          const tc: ToolCall = { name: msg.data.name, args: msg.data.args };
          pendingToolCalls.current.push(tc);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, toolCalls: [...pendingToolCalls.current] }
                : m
            )
          );
        }
        break;

      case "usage":
        setUsageInfo(typeof msg.data === "string" ? msg.data : JSON.stringify(msg.data));
        break;

      case "done":
        // Robustly clear streaming on any agent bubble (even if ref lost)
        setMessages((prev) =>
          prev.map((m) =>
            m.isStreaming ? { ...m, isStreaming: false } : m
          )
        );
        currentAgentMsgRef.current = null;
        pendingToolCalls.current = [];
        setIsThinking(false);
        setLastError(null);
        break;

      case "approval_request":
        setPendingApproval(msg.data as any);
        break;

      case "plan_request":
        setPendingPlan(msg.data as any);
        break;

      case "eval":
        setLastEval(msg.data as any);
        // Also append eval badge as agent message
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: "agent", content: `⭐ Eval — faithfulness ${(msg.data.scores?.faithfulness ?? 0).toFixed(2)} • relevance ${(msg.data.scores?.relevance ?? 0).toFixed(2)} • completeness ${(msg.data.scores?.completeness ?? 0).toFixed(2)} • groundedness ${(msg.data.scores?.groundedness ?? 0).toFixed(2)} — **${msg.data.quality_level || ""}**\n\n> ${msg.data.reasoning || ""}`, timestamp: Date.now() },
        ]);
        break;

      case "error": {
        const errText = `\n\n**Error:** ${msg.data}`;
        setLastError(msg.data);
        if (currentAgentMsgRef.current) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === currentAgentMsgRef.current
                ? { ...m, content: m.content + errText, isStreaming: false }
                : m
            )
          );
        } else {
          // No active bubble (e.g. quota hit before streaming) -> create one so error is visible and no spinner hangs
          const errId = nextId();
          setMessages((prev) => [
            ...prev,
            { id: errId, role: "agent", content: errText.trimStart(), timestamp: Date.now(), isStreaming: false },
          ]);
        }
        currentAgentMsgRef.current = null;
        pendingToolCalls.current = [];
        setIsThinking(false);
        break;
      }
    }
  }, []);

  const { status, sendChat, sendReset, sendLoadSession, sendSaveSession, sendApproval, sendPlanApproval } = useWebSocket({
    url: backendUrl,
    token,
    onMessage: handleWsMessage,
  });

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isThinking) { return; }
    lastUserMsgRef.current = text;
    setLastError(null);

    // Save to history (dedup consecutive)
    if (inputHistory.current[inputHistory.current.length - 1] !== text) {
      inputHistory.current.push(text);
      if (inputHistory.current.length > 50) inputHistory.current.shift();
    }
    historyIndex.current = -1;
    draftInput.current = "";

    // Add user message
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: text, timestamp: Date.now() },
    ]);
    sendChat(text);
    setInput("");

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [input, isThinking, sendChat]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Escape") {
      if (input) {
        e.preventDefault();
        setInput("");
        historyIndex.current = -1;
        draftInput.current = "";
        if (textareaRef.current) textareaRef.current.style.height = "auto";
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
      return;
    }
    // History recall: Up/Down like terminal (always works for single-line, for multiline only at edges)
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      if (inputHistory.current.length === 0) return;
      const el = e.currentTarget as HTMLTextAreaElement;
      const hasNewline = el.value.includes("\n");
      // Allow history when single-line, or when multiline but cursor at boundary
      if (hasNewline) {
        const atTop = el.selectionStart === 0;
        const atBottom = el.selectionEnd === el.value.length;
        if (e.key === "ArrowUp" && !atTop) return;
        if (e.key === "ArrowDown" && !atBottom) return;
      }
      e.preventDefault();
      if (historyIndex.current === -1) draftInput.current = input;
      if (e.key === "ArrowUp") {
        if (historyIndex.current < inputHistory.current.length - 1) {
          historyIndex.current += 1;
          const idx = inputHistory.current.length - 1 - historyIndex.current;
          const next = inputHistory.current[idx];
          setInput(next);
          requestAnimationFrame(() => {
            if (textareaRef.current) {
              textareaRef.current.style.height = "auto";
              textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + "px";
              textareaRef.current.selectionStart = textareaRef.current.selectionEnd = next.length;
            }
          });
        }
      } else {
        if (historyIndex.current > 0) {
          historyIndex.current -= 1;
          const idx = inputHistory.current.length - 1 - historyIndex.current;
          const next = inputHistory.current[idx];
          setInput(next);
          requestAnimationFrame(() => {
            if (textareaRef.current) {
              textareaRef.current.style.height = "auto";
              textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + "px";
              textareaRef.current.selectionStart = textareaRef.current.selectionEnd = next.length;
            }
          });
        } else if (historyIndex.current === 0) {
          historyIndex.current = -1;
          const next = draftInput.current;
          setInput(next);
          requestAnimationFrame(() => {
            if (textareaRef.current) {
              textareaRef.current.style.height = "auto";
              textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + "px";
              textareaRef.current.selectionStart = textareaRef.current.selectionEnd = next.length;
            }
          });
        }
      }
    }
  };

  const handleReset = () => {
    sendReset();
    setMessages([]);
    setUsageInfo("");
  };

  // Auto-resize textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  };

  return (
    <div className="chat-panel">
      <div className="chat-toolbar">
        <SessionPicker
          backendUrl={backendUrl}
          token={token}
          onSelectSession={sendLoadSession}
          onNewSession={handleReset}
          onSaveSession={sendSaveSession}
        />
        <StatusBar status={status} usage={usageInfo} isThinking={isThinking} backendUrl={backendUrl} token={token} />
      </div>

      {pendingApproval && (
        <div className="approval-dialog">
          <div className="approval-header">⚠️ Approval required</div>
          <div className="approval-tool">Tool: <code>{pendingApproval.tool}</code></div>
          <pre className="approval-preview">{pendingApproval.preview || JSON.stringify(pendingApproval.args, null, 2)}</pre>
          <div className="approval-actions">
            <button className="approval-btn approve" onClick={() => { sendApproval(pendingApproval.id, true); setPendingApproval(null); }}>Approve</button>
            <button className="approval-btn deny" onClick={() => { sendApproval(pendingApproval.id, false); setPendingApproval(null); }}>Deny</button>
          </div>
        </div>
      )}

      {pendingPlan && (
        <div className="approval-dialog" style={{ borderColor: "#0e639c" }}>
          <div className="approval-header">📋 Plan approval required</div>
          <pre className="approval-preview" style={{ maxHeight: 250 }}>{pendingPlan.markdown}</pre>
          <div className="approval-actions">
            <button className="approval-btn approve" onClick={() => { sendPlanApproval(pendingPlan.id, true); setPendingPlan(null); }}>Approve Plan</button>
            <button className="approval-btn deny" onClick={() => { sendPlanApproval(pendingPlan.id, false); setPendingPlan(null); }}>Deny Plan</button>
          </div>
        </div>
      )}

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-title">Send a message to start coding</div>
            <p className="chat-empty-hint">
              Ask Helix to read, edit, or explain code in your workspace.
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {lastError && (
          <div className="error-retry">
            <span style={{ fontSize: 11, color: "var(--fg-muted)", marginRight: 8 }}>{lastError.slice(0,120)}</span>
            <button onClick={() => { if (lastUserMsgRef.current) { setMessages((prev)=>[...prev,{id: nextId(), role:"user", content:lastUserMsgRef.current, timestamp:Date.now()}]); sendChat(lastUserMsgRef.current); setLastError(null); setIsThinking(true); } }}>Retry</button>
            <button style={{ marginLeft: 6 }} onClick={() => setLastError(null)}>Dismiss</button>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder={isThinking ? "Agent is thinking…" : "Ask the agent… (Shift+Enter for new line)"}
          disabled={status !== "connected"}
          rows={1}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!input.trim() || isThinking || status !== "connected"}
          title={isThinking ? "Thinking…" : "Send message"}
        >
          {isThinking ? (
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="spin-animate">
              <path d="M8 2a6 6 0 1 0 6 6" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
};
