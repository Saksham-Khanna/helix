/**
 * useTheme — syncs with VS Code's current color theme via CSS variables.
 *
 * VS Code injects CSS custom properties (--vscode-editor-background, etc.)
 * into the webview. This hook reads a few key ones for use in JS.
 */

import { useEffect, useState } from "react";

interface ThemeColors {
  background: string;
  foreground: string;
  editorBackground: string;
  inputBackground: string;
  inputBorder: string;
  buttonBackground: string;
  buttonForeground: string;
  isDark: boolean;
}

function isThemeDark(bg: string): boolean {
  if (typeof document !== "undefined" && document.body) {
    if (document.body.classList.contains("vscode-light")) return false;
    if (
      document.body.classList.contains("vscode-dark") ||
      document.body.classList.contains("vscode-high-contrast") ||
      document.body.classList.contains("vscode-high-contrast-light") === false
    ) {
      if (document.body.classList.contains("vscode-dark") || document.body.classList.contains("vscode-high-contrast")) {
        return true;
      }
    }
  }

  if (bg.startsWith("#")) {
    const hex = bg.slice(1);
    const r = parseInt(hex.substring(0, 2), 16) || 0;
    const g = parseInt(hex.substring(2, 4), 16) || 0;
    const b = parseInt(hex.substring(4, 6), 16) || 0;
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
  }

  const match = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (match) {
    const r = parseInt(match[1], 10);
    const g = parseInt(match[2], 10);
    const b = parseInt(match[3], 10);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
  }

  return true;
}

function readTheme(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  const bg = style.getPropertyValue("--vscode-editor-background").trim() || "#1e1e1e";
  const fg = style.getPropertyValue("--vscode-editor-foreground").trim() || "#d4d4d4";

  return {
    background: style.getPropertyValue("--vscode-sideBar-background").trim() || bg,
    foreground: fg,
    editorBackground: bg,
    inputBackground: style.getPropertyValue("--vscode-input-background").trim() || "#3c3c3c",
    inputBorder: style.getPropertyValue("--vscode-input-border").trim() || "#3c3c3c",
    buttonBackground: style.getPropertyValue("--vscode-button-background").trim() || "#0e639c",
    buttonForeground: style.getPropertyValue("--vscode-button-foreground").trim() || "#ffffff",
    isDark: isThemeDark(bg),
  };
}

export function useTheme(): ThemeColors {
  const [theme, setTheme] = useState<ThemeColors>(readTheme());

  useEffect(() => {
    // Re-read on theme change (VS Code fires a class change on body)
    const observer = new MutationObserver(() => setTheme(readTheme()));
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return theme;
}
