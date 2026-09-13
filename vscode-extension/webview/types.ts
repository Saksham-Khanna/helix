/**
 * Shared TypeScript types for the Agentic IDE webview.
 */

// ---- Chat messages ----

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  timestamp: number;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
}

export interface ToolCall {
  name: string;
  args: Record<string, any>;
  result?: string;
  duration?: number;
}

// ---- WebSocket protocol (from FastAPI backend) ----

export interface WsTextMessage {
  type: "text";
  data: string;
}

export interface WsToolMessage {
  type: "tool";
  data: { name: string; args: Record<string, any> };
}

export interface WsEvalMessage {
  type: "eval";
  data: Record<string, any>;
}

export interface WsUsageMessage {
  type: "usage";
  data: string;
}

export interface WsDoneMessage {
  type: "done";
}

export interface WsStatusMessage {
  type: "status";
  data: string;
}

export interface WsErrorMessage {
  type: "error";
  data: string;
}

export interface WsApprovalRequestMessage {
  type: "approval_request";
  data: { id: string; tool: string; args: Record<string, any>; preview: string };
}

export interface WsPlanRequestMessage {
  type: "plan_request";
  data: { id: string; plan: Record<string, any> | null; markdown: string };
}

export type WsIncoming =
  | WsTextMessage
  | WsToolMessage
  | WsEvalMessage
  | WsUsageMessage
  | WsDoneMessage
  | WsStatusMessage
  | WsErrorMessage
  | WsApprovalRequestMessage
  | WsPlanRequestMessage;

// ---- File tree ----

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "dir";
  size?: number;
  children?: FileNode[];
}

// ---- Session ----

export interface SessionInfo {
  session_id: string;
  title: string;
  provider: string;
  turn_count: number;
  updated_at: string;
  created_at: string;
}

// ---- Active tab ----

export type TabId = "chat" | "files" | "diff";
