import React, { useEffect, useState, useCallback } from "react";
import type { SessionInfo } from "../types";

interface Props {
  backendUrl: string;
  token: string;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onSaveSession: (name?: string) => void;
  activeSessionId?: string;
}

const RefreshIcon: React.FC<{ spinning?: boolean }> = ({ spinning }) => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={spinning ? "spin-animate" : ""}
  >
    <path d="M2 8a6 6 0 1 1 1.76 4.24" />
    <path d="M2 12V8h4" />
  </svg>
);

export const SessionPicker: React.FC<Props> = ({
  backendUrl,
  token,
  onSelectSession,
  onNewSession,
  onSaveSession,
  activeSessionId,
}) => {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);

  const fetchSessions = useCallback(async () => {
    if (!backendUrl) return;
    setLoading(true);
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${backendUrl}/api/sessions`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch {
      // ignore network errors when offline
    } finally {
      setLoading(false);
    }
  }, [backendUrl, token]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleSave = () => {
    onSaveSession(saveName.trim() || undefined);
    setSaveName("");
    setShowSaveInput(false);
    setTimeout(fetchSessions, 600);
  };

  // Close popups on outside click
  useEffect(() => {
    if (!isOpen && !showSaveInput) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest(".session-picker")) {
        setIsOpen(false);
        setShowSaveInput(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [isOpen, showSaveInput]);

  return (
    <div className="session-picker">
      <div className="session-bar">
        <button
          className="toolbar-btn session-toggle-btn"
          onClick={() => {
            const next = !isOpen;
            setIsOpen(next);
            if (next) setShowSaveInput(false);
            if (next) fetchSessions();
          }}
          title="Manage sessions"
        >
          Sessions ({sessions.length})
        </button>
        <button
          className="toolbar-btn"
          onClick={onNewSession}
          title="Start fresh conversation"
        >
          + New
        </button>
        <button
          className="toolbar-btn"
          onClick={() => {
            const next = !showSaveInput;
            setShowSaveInput(next);
            if (next) setIsOpen(false);
          }}
          title="Save conversation checkpoint"
        >
          Save
        </button>
      </div>

      {showSaveInput && (
        <div className="session-save-row">
          <input
            type="text"
            className="session-save-input"
            placeholder="Session name (optional)..."
            value={saveName}
            autoFocus
            onChange={(e) => setSaveName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") setShowSaveInput(false);
            }}
          />
          <button className="toolbar-btn primary-btn" onClick={handleSave}>
            Save
          </button>
          <button
            className="toolbar-btn"
            onClick={() => setShowSaveInput(false)}
          >
            Cancel
          </button>
        </div>
      )}

      {isOpen && (
        <div className={`session-dropdown ${showSaveInput ? "with-save-row" : ""}`}>
          <div className="session-dropdown-header">
            <span>Saved Sessions</span>
            <button
              className="icon-btn"
              onClick={fetchSessions}
              title="Refresh sessions"
              disabled={loading}
            >
              <RefreshIcon spinning={loading} />
            </button>
          </div>
          <div className="session-list">
            {loading && <div className="session-loading">Loading sessions...</div>}
            {!loading && sessions.length === 0 && (
              <div className="session-empty">No saved sessions yet</div>
            )}
            {sessions.map((s) => (
              <div
                key={s.session_id}
                className={`session-item ${activeSessionId === s.session_id ? "active" : ""}`}
                onClick={() => {
                  onSelectSession(s.session_id);
                  setIsOpen(false);
                }}
              >
                <div className="session-item-title">
                  {s.title || s.session_id}
                </div>
                <div className="session-item-meta">
                  <span>{s.turn_count || 0} turns</span>
                  {s.updated_at && (
                    <span>• {new Date(s.updated_at).toLocaleDateString()}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
