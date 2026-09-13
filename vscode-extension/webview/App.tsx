import React, { useState, useEffect } from "react";
import type { TabId } from "./types";
import { useVSCode } from "./hooks/useVSCode";
import { ChatPanel } from "./components/ChatPanel";
import { FileTree } from "./components/FileTree";
import { FileEditor } from "./components/FileEditor";
import { DiffViewer } from "./components/DiffViewer";

const ChatTabIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2.5 3.5h11a1 1 0 0 1 1 1v6.5a1 1 0 0 1-1 1H5.5L2.5 14.5V4.5a1 1 0 0 1 1-1z" />
  </svg>
);

const FilesTabIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1.5 3.5h4l1.5 2h7.5v8H1.5v-10z" />
  </svg>
);

const DiffTabIcon = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="4.5" cy="4.5" r="2" />
    <circle cx="11.5" cy="11.5" r="2" />
    <path d="M4.5 6.5v5M11.5 4.5v5" strokeDasharray="2 2" />
  </svg>
);

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>("chat");
  const [backendUrl, setBackendUrl] = useState<string>("http://localhost:8000");
  const [token, setToken] = useState<string>("");
  const [activeFilePath, setActiveFilePath] = useState<string | undefined>(undefined);
  const [diffState, setDiffState] = useState<{
    filePath?: string;
    original?: string;
    modified?: string;
  }>({});
  const [showTreeInEditor, setShowTreeInEditor] = useState<boolean>(true);

  const { onMessage, postMessage } = useVSCode();

  useEffect(() => {
    postMessage({ type: "webviewReady" });
    return onMessage((msg: any) => {
      if (!msg) return;
      switch (msg.type) {
        case "setBackendUrl":
          if (msg.url) setBackendUrl(msg.url);
          if (msg.token !== undefined) setToken(msg.token);
          break;

        case "openFile":
          if (msg.path) {
            setActiveFilePath(msg.path);
            setActiveTab("files");
          }
          break;

        case "sendSelection":
          setActiveTab("chat");
          break;
      }
    });
  }, [onMessage]);

  const handleSelectFile = (path: string) => {
    setActiveFilePath(path);
  };

  return (
    <div className="app-container">
      <header className="app-tabs-header">
        <div className="tab-list" role="tablist">
          <button
            role="tab"
            aria-selected={activeTab === "chat"}
            className={`tab-btn ${activeTab === "chat" ? "active" : ""}`}
            onClick={() => setActiveTab("chat")}
          >
            <span className="tab-icon"><ChatTabIcon /></span>
            <span>Chat</span>
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "files"}
            className={`tab-btn ${activeTab === "files" ? "active" : ""}`}
            onClick={() => setActiveTab("files")}
          >
            <span className="tab-icon"><FilesTabIcon /></span>
            <span>Files</span>
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "diff"}
            className={`tab-btn ${activeTab === "diff" ? "active" : ""}`}
            onClick={() => setActiveTab("diff")}
          >
            <span className="tab-icon"><DiffTabIcon /></span>
            <span>Changes</span>
          </button>
        </div>
      </header>

      <main className="app-body">
        {activeTab === "chat" && (
          <ChatPanel backendUrl={backendUrl} token={token} />
        )}

        {activeTab === "files" && (
          <div className="files-view-container">
            <div className={`files-sidebar ${showTreeInEditor ? "open" : "collapsed"}`}>
              <div className="sidebar-toggle-row">
                <button
                  className="sidebar-toggle-btn"
                  onClick={() => setShowTreeInEditor(!showTreeInEditor)}
                  title={showTreeInEditor ? "Hide file tree" : "Show file tree"}
                >
                  {showTreeInEditor ? "‹ Folders" : "› Folders"}
                </button>
              </div>
              {showTreeInEditor && (
                <FileTree
                  backendUrl={backendUrl}
                  token={token}
                  onSelectFile={handleSelectFile}
                  selectedPath={activeFilePath}
                />
              )}
            </div>
            <div className="files-editor-area">
              <FileEditor
                backendUrl={backendUrl}
                token={token}
                filePath={activeFilePath}
                onClose={() => setActiveFilePath(undefined)}
              />
            </div>
          </div>
        )}

        {activeTab === "diff" && (
          <DiffViewer
            backendUrl={backendUrl}
            token={token}
            filePath={diffState.filePath}
            originalContent={diffState.original}
            modifiedContent={diffState.modified}
          />
        )}
      </main>
    </div>
  );
};

export default App;
