import React, { useEffect, useState } from "react";
import type { ConnectionStatus } from "../hooks/useWebSocket";

interface Props {
  status: ConnectionStatus;
  usage?: string;
  isThinking?: boolean;
  backendUrl?: string;
  token?: string;
}

export const StatusBar: React.FC<Props> = ({ status, usage, isThinking, backendUrl, token }) => {
  const [health, setHealth] = useState<{ provider?: string; model?: string; planner_enabled?: boolean } | null>(null);

  useEffect(() => {
    if (!backendUrl) return;
    const fetchHealth = async () => {
      try {
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const res = await fetch(`${backendUrl}/api/health`, { headers });
        if (res.ok) {
          const data = await res.json();
          setHealth(data);
        }
      } catch {}
    };
    fetchHealth();
    const id = setInterval(fetchHealth, 10000);
    return () => clearInterval(id);
  }, [backendUrl, token]);
  const statusColors: Record<ConnectionStatus, string> = {
    connected: "var(--vscode-testing-iconPassed, #4ec9b0)",
    connecting: "var(--vscode-editorWarning-foreground, #cca700)",
    disconnected: "var(--vscode-descriptionForeground, #8c8c8c)",
  };

  const statusTooltips: Record<ConnectionStatus, string> = {
    connected: "Connected to Helix backend",
    connecting: "Connecting to Helix backend…",
    disconnected: "Disconnected from Helix backend",
  };

  return (
    <div className="status-bar-container">
      <div className="status-indicator" title={statusTooltips[status]}>
        <span
          className={`status-dot ${isThinking ? "thinking" : ""}`}
          style={{ backgroundColor: statusColors[status] }}
        />
      </div>
      {health?.provider && (
        <span className="status-usage" title={`${health.provider} / ${health.model || ""}`}>
          {health.provider}{health.model ? `:${health.model}` : ""}{health.planner_enabled ? " • planner" : ""}
        </span>
      )}
      {usage && (
        <div className="status-usage" title="Session token usage">
          <span>{usage}</span>
        </div>
      )}
    </div>
  );
};

