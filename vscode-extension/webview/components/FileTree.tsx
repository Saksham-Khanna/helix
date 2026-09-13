import React, { useState, useEffect, useCallback } from "react";
import type { FileNode } from "../types";

interface Props {
  backendUrl: string;
  token: string;
  onSelectFile: (path: string) => void;
  selectedPath?: string;
}

const FolderIcon: React.FC = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1.5 3.5h4l1.5 2h7.5v8H1.5v-10z" />
  </svg>
);

const FileIcon: React.FC = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 2.5h6.5l3.5 3.5V13.5a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z" />
    <path d="M9.5 2.5v3.5h3.5" />
  </svg>
);

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

function formatBytes(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface TreeNodeProps {
  node: FileNode;
  depth: number;
  onSelectFile: (path: string) => void;
  selectedPath?: string;
  filter: string;
}

const TreeNode: React.FC<TreeNodeProps> = ({
  node,
  depth,
  onSelectFile,
  selectedPath,
  filter,
}) => {
  const [expanded, setExpanded] = useState(true);

  if (node.type === "dir") {
    // If filtering, check if any children match
    const matchingChildren = node.children || [];
    return (
      <div className="file-tree-dir">
        <div
          className="file-tree-item dir-item"
          style={{ paddingLeft: `${depth * 14 + 6}px` }}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="file-tree-arrow">{expanded ? "▾" : "▸"}</span>
          <span className="file-tree-icon"><FolderIcon /></span>
          <span className="file-tree-name">{node.name}</span>
        </div>
        {expanded && (
          <div className="file-tree-children">
            {matchingChildren.map((child) => (
              <TreeNode
                key={child.path}
                node={child}
                depth={depth + 1}
                onSelectFile={onSelectFile}
                selectedPath={selectedPath}
                filter={filter}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  // File item
  if (filter && !node.name.toLowerCase().includes(filter.toLowerCase()) && !node.path.toLowerCase().includes(filter.toLowerCase())) {
    return null;
  }

  const isSelected = selectedPath === node.path;

  return (
    <div
      className={`file-tree-item file-item ${isSelected ? "selected" : ""}`}
      style={{ paddingLeft: `${depth * 14 + 18}px` }}
      onClick={() => onSelectFile(node.path)}
      title={node.path}
    >
      <span className="file-tree-icon"><FileIcon /></span>
      <span className="file-tree-name">{node.name}</span>
      {node.size !== undefined && (
        <span className="file-tree-size">{formatBytes(node.size)}</span>
      )}
    </div>
  );
};

export const FileTree: React.FC<Props> = ({
  backendUrl,
  token,
  onSelectFile,
  selectedPath,
}) => {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const fetchFiles = useCallback(async () => {
    if (!backendUrl) return;
    setLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${backendUrl}/api/files`, { headers });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setTree(data.tree || []);
    } catch (e: any) {
      setError(e.message || "Failed to load files");
    } finally {
      setLoading(false);
    }
  }, [backendUrl, token]);

  useEffect(() => {
    fetchFiles();
    const id = setInterval(fetchFiles, 5000);
    const onFocus = () => fetchFiles();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [fetchFiles]);

  return (
    <div className="file-tree-container">
      <div className="file-tree-header">
        <span className="file-tree-title">Workspace Files</span>
        <div className="file-tree-actions">
          <button
            className="icon-btn"
            onClick={fetchFiles}
            title="Refresh file tree"
            disabled={loading}
          >
            <RefreshIcon spinning={loading} />
          </button>
        </div>
      </div>

      <div className="file-tree-search">
        <input
          type="text"
          className="file-search-input"
          placeholder="Filter files..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {filter && (
          <button
            className="file-search-clear"
            onClick={() => setFilter("")}
          >
            ×
          </button>
        )}
      </div>

      <div className="file-tree-content">
        {loading && <div className="file-tree-msg">Loading files...</div>}
        {error && <div className="file-tree-msg error">Error: {error}</div>}
        {!loading && !error && tree.length === 0 && (
          <div className="file-tree-msg">Workspace is empty</div>
        )}
        {!loading &&
          tree.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              depth={0}
              onSelectFile={onSelectFile}
              selectedPath={selectedPath}
              filter={filter}
            />
          ))}
      </div>
    </div>
  );
};
