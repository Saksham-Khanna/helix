import React from "react";
import type { ConnectionStatus } from "../hooks/useWebSocket";

interface Props {
  status: ConnectionStatus;
  usage?: string;
  isThinking?: boolean;
}

export const StatusBar: React.FC<Props> = ({ status, usage, isThinking }) => {
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
      {usage && (
        <div className="status-usage" title="Session token usage">
          <span>{usage}</span>
        </div>
      )}
    </div>
  );
};

