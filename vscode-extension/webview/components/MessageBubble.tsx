import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { ToolCallCard } from "./ToolCallCard";

interface Props {
  message: ChatMessage;
}

export const MessageBubble: React.FC<Props> = ({ message }) => {
  const isUser = message.role === "user";
  const isError = !isUser && (message.content.includes("**Error:**") || message.content.includes("Rate limit") || message.content.includes("Groq API error"));

  return (
    <div className={`message-bubble ${isUser ? "message-user" : "message-agent"} ${isError ? "message-error" : ""}`}>
      <div className="message-role">
        {isUser ? "You" : "Agent"}
      </div>
      <div className="message-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ className, children, ...props }) {
              const isInline = !className;
              if (isInline) {
                return <code className="inline-code" {...props}>{children}</code>;
              }
              const language = className?.replace("language-", "") || "";
              return (
                <div className="code-block">
                  <div className="code-block-header">
                    <span>{language}</span>
                  </div>
                  <pre><code className={className} {...props}>{children}</code></pre>
                </div>
              );
            },
            table({ children, ...props }) {
              return <table className="markdown-table" {...props}>{children}</table>;
            },
            a({ children, href, ...props }) {
              return <a href={href} target="_blank" rel="noopener noreferrer" {...(props as any)}>{children}</a>;
            },
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="message-tool-calls">
          {message.toolCalls.map((tc, idx) => (
            <ToolCallCard key={idx} toolCall={tc} />
          ))}
        </div>
      )}
      {message.isStreaming && !message.content && (
        <span className="streaming-cursor">● thinking…</span>
      )}
      {message.isStreaming && message.content && (
        <span className="streaming-cursor streaming-cursor-inline">▋</span>
      )}
    </div>
  );
};

