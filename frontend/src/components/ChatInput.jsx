import { useState } from "react";

export default function ChatInput({ mode, lastAsk, onSend, disabled }) {
  const [text, setText] = useState("");

  function normalizeBudgetIfNeeded(raw) {
    const digitsOnly = /^\s*\d{2,5}\s*$/.test(raw);
    if (digitsOnly) return raw.trim() + " dollars";
    return raw;
  }

  return (
    <div className="flex gap-2 items-center">
      <input
        className="input"
        placeholder={mode === "Describe" ? "Describe your ideal phone…" : "Type your message…"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && text.trim()) {
            onSend(normalizeBudgetIfNeeded(text));
            setText("");
          }
        }}
        disabled={disabled}
      />
      <button
        className="btn"
        onClick={() => {
          if (!text.trim()) return;
          onSend(normalizeBudgetIfNeeded(text));
          setText("");
        }}
        disabled={disabled}
      >
        Send
      </button>
    </div>
  );
}
