import React, { useState, useEffect, useCallback } from "react";
import { DiffEditor, Editor } from "@monaco-editor/react";
import { useTheme } from "../hooks/useTheme";

interface Props {
  backendUrl: string;
  token: string;
  filePath?: string;
  originalContent?: string;
  modifiedContent?: string;
}

export const DiffViewer: React.FC<Props> = ({
  backendUrl,
  token,
  filePath,
  originalContent,
  modifiedContent,
}) => {
  const [workspaceDiff, setWorkspaceDiff] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [sideBySide, setSideBySide] = useState(true);
  const theme = useTheme();

  const hasDirectDiff =
    originalContent !== undefined && modifiedContent !== undefined;

  const fetchWorkspaceDiff = useCallback(async () => {
    if (!backendUrl) return;
    setLoading(true);
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${backendUrl}/api/diff`, { headers });
      if (res.ok) {
        const data = await res.json();
        setWorkspaceDiff(data.diff || "");
      }
    } catch {
      // ignore offline errors
    } finally {
      setLoading(false);
    }
  }, [backendUrl, token]);

  useEffect(() => {
    if (!hasDirectDiff) {
      fetchWorkspaceDiff();
      // Auto-refresh every 3s while tab is visible
      const id = setInterval(fetchWorkspaceDiff, 3000);
      const onFocus = () => fetchWorkspaceDiff();
      window.addEventListener("focus", onFocus);
      return () => {
        clearInterval(id);
        window.removeEventListener("focus", onFocus);
      };
    }
  }, [hasDirectDiff, fetchWorkspaceDiff]);

  const monacoTheme = theme.isDark ? "vs-dark" : "light";

  // Parse workspace diff into human summary — easy to understand
  const diffStats = React.useMemo(() => {
    if (!workspaceDiff.trim() || hasDirectDiff) return null;
    const files = [...workspaceDiff.matchAll(/^diff --git a\/(.+?) b\//gm)].map((m) => m[1]);
    let added = 0, removed = 0;
    for (const line of workspaceDiff.split("\n")) {
      if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) continue;
      if (line.startsWith("+")) added++;
      else if (line.startsWith("-")) removed++;
    }
    return { files, fileCount: files.length, added, removed };
  }, [workspaceDiff, hasDirectDiff]);

  // Determine language for file diff
  const ext = filePath?.split(".").pop()?.toLowerCase();
  const langMap: Record<string, string> = {
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    html: "html",
    css: "css",
    md: "markdown",
  };
  const language = (ext && langMap[ext]) || "plaintext";

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

const CheckIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

  return (
    <div className="diff-viewer-container">
      <div className="diff-viewer-bar">
        <div className="diff-viewer-info">
          <span className="diff-viewer-title">
            {hasDirectDiff
              ? `Diff: ${filePath || "Current Changes"}`
              : "Workspace Changes"}
          </span>
          {!hasDirectDiff && diffStats && diffStats.fileCount > 0 && (
            <span style={{ marginLeft: 10, fontSize: 11, color: "var(--fg-muted)" }}>
              <span style={{ color: "#4ec9b0" }}>+{diffStats.added}</span>
              {" / "}
              <span style={{ color: "#f14c4c" }}>-{diffStats.removed}</span>
              {" • "}
              {diffStats.fileCount} file{diffStats.fileCount > 1 ? "s" : ""} changed
            </span>
          )}
        </div>
        <div className="diff-viewer-actions">
          {hasDirectDiff && (
            <button
              className="toolbar-btn"
              onClick={() => setSideBySide(!sideBySide)}
              title="Toggle side-by-side or inline view"
            >
              {sideBySide ? "Inline View" : "Side-by-Side"}
            </button>
          )}
          {!hasDirectDiff && (
            <button
              className="icon-btn"
              onClick={fetchWorkspaceDiff}
              title="Refresh workspace diff"
              disabled={loading}
            >
              <RefreshIcon spinning={loading} />
            </button>
          )}
        </div>
      </div>

      <div className="diff-viewer-content">
        {loading ? (
          <div className="diff-loading">Loading diff...</div>
        ) : hasDirectDiff ? (
          <DiffEditor
            height="100%"
            language={language}
            original={originalContent}
            modified={modifiedContent}
            theme={monacoTheme}
            options={{
              readOnly: true,
              renderSideBySide: sideBySide,
              automaticLayout: true,
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: "var(--vscode-editor-font-family, Consolas, monospace)",
              scrollBeyondLastLine: false,
            }}
          />
        ) : workspaceDiff.trim() ? (
          <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
            {diffStats && (
              <div style={{ padding: "8px 12px", background: "var(--card-bg)", borderBottom: "1px solid var(--border-color)", fontSize: 12, lineHeight: 1.6 }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Summary — easy to read:</div>
                {diffStats.files.length > 0 ? (
                  <ul style={{ margin: "4px 0 6px 18px", padding: 0 }}>
                    {diffStats.files.map((f) => (
                      <li key={f} style={{ marginBottom: 2 }}><code style={{ background: "rgba(128,128,128,0.15)", padding: "1px 4px", borderRadius: 3 }}>{f}</code> — changed</li>
                    ))}
                  </ul>
                ) : (
                  <div>Files changed</div>
                )}
                <div style={{ color: "var(--fg-muted)", fontSize: 11 }}>
                  <span style={{ color: "#4ec9b0", fontWeight: 600 }}>+{diffStats.added} lines added</span>
                  {"  "} <span style={{ color: "#f14c4c", fontWeight: 600 }}>-{diffStats.removed} lines removed</span>
                  <br />
                  <span>Green `+` = naya code, Red `-` = hata hua code. Har file ka diff neeche dikh raha hai.</span>
                </div>
              </div>
            )}
            <div style={{ flex: 1, minHeight: 0 }}>
              <Editor
                height="100%"
                language="diff"
                theme={monacoTheme}
                value={workspaceDiff}
                options={{
                  readOnly: true,
                  automaticLayout: true,
                  minimap: { enabled: false },
                  fontSize: 13,
                  fontFamily: "var(--vscode-editor-font-family, Consolas, monospace)",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                }}
              />
            </div>
          </div>
        ) : (
          <div className="diff-empty">
            <div className="diff-empty-icon"><CheckIcon /></div>
            <p>No changes detected.</p>
            <p className="diff-empty-hint">
              Workspace matches the latest saved state.<br />
              Agent jab `edit_file` / `write_file` karega to yahan file list + green/red diff ayega.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
