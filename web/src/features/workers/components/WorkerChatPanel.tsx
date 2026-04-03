"use client";

import { useCallback, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAppState, useAppDispatch } from "../state/store";
import { sendChatMessage } from "@/lib/api";

export function WorkerChatPanel() {
  const { chatMessages, chatInput, isChatLoading, showThinking } = useAppState();
  const dispatch = useAppDispatch();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const handleSend = useCallback(async () => {
    const text = chatInput.trim();
    if (!text || isChatLoading) return;

    const userMsg = {
      id: `user-${Date.now()}`,
      role: "user" as const,
      content: text,
      timestamp: new Date().toISOString(),
    };

    dispatch({ type: "ADD_CHAT_MESSAGE", message: userMsg });
    dispatch({ type: "SET_CHAT_INPUT", input: "" });
    dispatch({ type: "SET_CHAT_LOADING", loading: true });

    try {
      const res = await sendChatMessage({ message: text });
      dispatch({
        type: "ADD_CHAT_MESSAGE",
        message: {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: res.reply,
          thinking: res.thinking,
          timestamp: new Date().toISOString(),
        },
      });
    } catch (err) {
      dispatch({
        type: "ADD_CHAT_MESSAGE",
        message: {
          id: `error-${Date.now()}`,
          role: "system",
          content: `Error: ${err instanceof Error ? err.message : "Failed to send message"}`,
          timestamp: new Date().toISOString(),
        },
      });
    } finally {
      dispatch({ type: "SET_CHAT_LOADING", loading: false });
    }
  }, [chatInput, isChatLoading, dispatch]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex flex-col h-full">
      {/* Chat Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: "var(--border-dim)" }}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">🤖</span>
          <span className="font-medium text-sm" style={{ color: "var(--text-primary)" }}>
            AI Assistant
          </span>
        </div>
        <button
          onClick={() => dispatch({ type: "TOGGLE_THINKING" })}
          className="mono-text text-xs px-2 py-1 rounded transition-colors"
          style={{
            background: showThinking ? "var(--accent-cyan)" : "var(--bg-tertiary)",
            color: showThinking ? "var(--bg-primary)" : "var(--text-muted)",
          }}
        >
          Thinking
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <span className="text-4xl">🤖</span>
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              Onlime AI Assistant에게 질문하세요
            </p>
            <div className="flex flex-wrap gap-2 mt-2 max-w-md">
              {["오늘 일정 요약해줘", "최근 미팅 노트 보여줘", "녹음 동기화 상태는?"].map(
                (q) => (
                  <button
                    key={q}
                    onClick={() => dispatch({ type: "SET_CHAT_INPUT", input: q })}
                    className="mono-text text-xs px-3 py-1.5 rounded-full transition-colors"
                    style={{
                      border: "1px solid var(--border-medium)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {q}
                  </button>
                ),
              )}
            </div>
          </div>
        )}

        {chatMessages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className="max-w-[80%] rounded-lg px-4 py-3"
              style={{
                background:
                  msg.role === "user"
                    ? "var(--accent-cyan)"
                    : msg.role === "system"
                      ? "var(--status-error)"
                      : "var(--bg-tertiary)",
                color:
                  msg.role === "user" ? "var(--bg-primary)" : "var(--text-primary)",
              }}
            >
              {/* Thinking trace */}
              {showThinking && msg.thinking && (
                <details
                  className="mb-2 text-xs rounded p-2"
                  style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
                >
                  <summary className="cursor-pointer">Thinking...</summary>
                  <pre className="mt-1 whitespace-pre-wrap font-mono">{msg.thinking}</pre>
                </details>
              )}
              <div className="prose prose-sm prose-invert max-w-none text-sm [&_p]:m-0 [&_pre]:bg-black/20 [&_pre]:rounded [&_pre]:p-2 [&_code]:text-xs">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              </div>
              <span
                className="block text-[10px] mt-1 opacity-50"
                style={{ textAlign: msg.role === "user" ? "right" : "left" }}
              >
                {new Date(msg.timestamp).toLocaleTimeString("ko-KR", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          </div>
        ))}

        {isChatLoading && (
          <div className="flex justify-start">
            <div
              className="rounded-lg px-4 py-3"
              style={{ background: "var(--bg-tertiary)" }}
            >
              <div className="flex gap-1">
                <span className="w-2 h-2 rounded-full animate-bounce" style={{ background: "var(--accent-cyan)", animationDelay: "0ms" }} />
                <span className="w-2 h-2 rounded-full animate-bounce" style={{ background: "var(--accent-cyan)", animationDelay: "150ms" }} />
                <span className="w-2 h-2 rounded-full animate-bounce" style={{ background: "var(--accent-cyan)", animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        className="p-4 border-t shrink-0"
        style={{ borderColor: "var(--border-dim)" }}
      >
        <div
          className="flex items-end gap-2 rounded-lg p-2"
          style={{
            background: "var(--bg-tertiary)",
            border: "1px solid var(--border-medium)",
          }}
        >
          <textarea
            ref={inputRef}
            value={chatInput}
            onChange={(e) => dispatch({ type: "SET_CHAT_INPUT", input: e.target.value })}
            onKeyDown={handleKeyDown}
            placeholder="메시지를 입력하세요..."
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm outline-none"
            style={{
              color: "var(--text-primary)",
              maxHeight: 120,
              fontFamily: "var(--font-body)",
            }}
          />
          <button
            onClick={handleSend}
            disabled={!chatInput.trim() || isChatLoading}
            className="shrink-0 px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200 disabled:opacity-30"
            style={{
              background: "var(--accent-cyan)",
              color: "var(--bg-primary)",
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
