/**
 * useWebSocket — manages WebSocket connection to the FastAPI backend.
 *
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Typed message sending (chat, reset, load_session, save_session)
 * - Dispatches incoming messages via callbacks
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { WsIncoming } from "../types";

interface UseWebSocketOptions {
  url: string;
  token?: string;
  onMessage?: (msg: WsIncoming) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export function useWebSocket({ url, token, onMessage, onOpen, onClose }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef(1000);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) { return; }

    // Build WS URL from HTTP URL
    const wsUrl = url.replace(/^http/, "ws") + "/ws/chat" + (token ? `?token=${token}` : "");
    setStatus("connecting");

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      backoffRef.current = 1000;
      onOpen?.();
    };

    ws.onmessage = (event) => {
      try {
        const data: WsIncoming = JSON.parse(event.data);
        onMessageRef.current?.(data);
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      onClose?.();
      // Auto-reconnect with exponential backoff (max 30s)
      reconnectTimer.current = setTimeout(() => {
        backoffRef.current = Math.min(backoffRef.current * 2, 30000);
        connect();
      }, backoffRef.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [url, token, onOpen, onClose]);

  const disconnect = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  const sendChat = useCallback((message: string) => {
    wsRef.current?.send(JSON.stringify({ type: "chat", message }));
  }, []);

  const sendReset = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: "reset" }));
  }, []);

  const sendLoadSession = useCallback((sessionId: string) => {
    wsRef.current?.send(JSON.stringify({ type: "load_session", session_id: sessionId }));
  }, []);

  const sendSaveSession = useCallback((name?: string) => {
    wsRef.current?.send(JSON.stringify({ type: "save_session", name }));
  }, []);

  const sendApproval = useCallback((id: string, approved: boolean) => {
    wsRef.current?.send(JSON.stringify({ type: "approval_response", data: { id, approved } }));
  }, []);

  const sendPlanApproval = useCallback((id: string, approved: boolean) => {
    wsRef.current?.send(JSON.stringify({ type: "plan_response", data: { id, approved } }));
  }, []);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    if (url) { connect(); }
    return () => disconnect();
  }, [url, token]);

  return {
    status,
    sendChat,
    sendReset,
    sendLoadSession,
    sendSaveSession,
    sendApproval,
    sendPlanApproval,
    connect,
    disconnect,
  };
}
