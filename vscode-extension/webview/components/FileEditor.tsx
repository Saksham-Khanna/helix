import React, { useState, useEffect, useCallback, useRef } from "react";
import Editor, { Monaco } from "@monaco-editor/react";
import { useVSCode } from "../hooks/useVSCode";
import { useTheme } from "../hooks/useTheme";

interface Props {
  backendUrl: string;
  token: string;
  filePath?: string;
  onClose?: () => void;
}

function detectLanguage(path?: string): string {
  if (!path) return "plaintext";
  const ext = path.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "py":
      return "python";
    case "ts":
    case "tsx":
      return "typescript";
    case "js":
    case "jsx":
      return "javascript";
    case "json":
      return "json";
    case "html":
      return "html";
    case "css":
    case "scss":
    case "less":
      return "css";
    case "md":
      return "markdown";
    case "yaml":
    case "yml":
      return "yaml";
    case "toml":
    case "ini":
      return "ini";
    case "sh":
    case "bash":
    case "zsh":
      return "shell";
    case "sql":
      return "sql";
    case "xml":
    case "svg":
      return "xml";
    default:
      return "plaintext";
  }
}

export const FileEditor: React.FC<Props> = ({
  backendUrl,
  token,
  filePath,
  onClose,
}) => {
  const [content, setContent] = useState<string>("");
  const [initialContent, setInitialContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const theme = useTheme();
  const { postMessage } = useVSCode();
  const editorRef = useRef<any>(null);

  const isDirty = content !== initialContent;

  const loadFile = useCallback(async (path: string) => {
    if (!backendUrl || !path) return;
    setLoading(true);
    setStatusMsg(null);
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(
        `${backendUrl}/api/files/read?path=${encodeURIComponent(path)}`,
        { headers }
      );
      if (!res.ok) {
        throw new Error(`Failed to read: HTTP ${res.status}`);
      }
      const data = await res.json();
      setContent(data.content ?? "");
      setInitialContent(data.content ?? "");
    } catch (e: any) {
      setStatusMsg({ text: e.message || "Failed to load file", error: true });
    } finally {
      setLoading(false);
    }
  }, [backendUrl, token]);

  useEffect(() => {
    if (filePath) {
      loadFile(filePath);
    } else {
      setContent("");
      setInitialContent("");
    }
  }, [filePath, loadFile]);

  const handleSave = async () => {
    if (!backendUrl || !filePath || saving) return;
    setSaving(true);
    setStatusMsg(null);
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${backendUrl}/api/files/write`, {
        method: "POST",
        headers,
        body: JSON.stringify({ path: filePath, content }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `Save failed: HTTP ${res.status}`);
      }
      setInitialContent(content);
      setStatusMsg({ text: "Saved successfully!" });
      setTimeout(() => setStatusMsg(null), 2500);
    } catch (e: any) {
      setStatusMsg({ text: e.message || "Failed to save", error: true });
    } finally {
      setSaving(false);
    }
  };

  const handleOpenInVSCode = () => {
    if (filePath) {
      postMessage({
        type: "requestOpenFile",
        path: filePath,
      });
    }
  };

  const handleEditorMount = (editor: any, monaco: Monaco) => {
    editorRef.current = editor;
    // Bind Ctrl+S / Cmd+S
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave();
    });
  };

const DocumentIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
);

  if (!filePath) {
    return (
      <div className="file-editor-empty">
        <div className="file-editor-empty-icon"><DocumentIcon /></div>
        <p>No file selected.</p>
        <p className="file-editor-empty-hint">
          Choose a file from the workspace tree to view and edit.
        </p>
      </div>
    );
  }

  const language = detectLanguage(filePath);
  const monacoTheme = theme.isDark ? "vs-dark" : "light";

  return (
    <div className="file-editor-container">
      <div className="file-editor-bar">
        <div className="file-editor-info">
          <span className="file-editor-path">
            {filePath} {isDirty && <span className="dirty-indicator">●</span>}
          </span>
          <span className="file-editor-lang">{language}</span>
        </div>
        <div className="file-editor-actions">
          {statusMsg && (
            <span
              className={`file-editor-status ${statusMsg.error ? "error" : "success"}`}
            >
              {statusMsg.text}
            </span>
          )}
          <button
            className="toolbar-btn primary-btn"
            onClick={handleSave}
            disabled={!isDirty || saving || loading}
            title="Save changes (Ctrl+S)"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            className="toolbar-btn"
            onClick={handleOpenInVSCode}
            title="Open in VS Code native editor"
          >
            ↗ VS Code
          </button>
          {onClose && (
            <button className="icon-btn" onClick={onClose} title="Close editor">
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="file-editor-monaco">
        {loading ? (
          <div className="file-editor-loading">Loading file content...</div>
        ) : (
          <Editor
            height="100%"
            language={language}
            theme={monacoTheme}
            value={content}
            onChange={(val) => setContent(val ?? "")}
            onMount={handleEditorMount}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: "var(--vscode-editor-font-family, Consolas, monospace)",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
              wordWrap: "on",
              padding: { top: 8, bottom: 8 },
            }}
          />
        )}
      </div>
    </div>
  );
};
