"use client";

import { useState } from "react";
import { btnPrimary, btnSecondary } from "@/components/ui/states";
import { MAX_CHARS } from "@/lib/assistant/useChat";

export function Composer({
  disabled, disabledReason, streaming, onSend, onStop,
}: {
  disabled: boolean;
  disabledReason: string | null;
  streaming: boolean;
  onSend: (text: string) => boolean;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const tooLong = text.length > MAX_CHARS;
  const canSend = !disabled && !streaming && text.trim().length > 0 && !tooLong;

  const submit = () => {
    if (canSend && onSend(text)) setText("");
  };

  return (
    <form
      className="border-t border-line p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="assistant-input" className="sr-only">Ask about weather or air quality</label>
      <div className="flex items-end gap-2">
        <textarea
          id="assistant-input"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          disabled={disabled}
          placeholder={disabled ? "The assistant is not available" : "Ask about weather or air quality (Enter to send, Shift+Enter for a new line)"}
          aria-describedby="assistant-input-help"
          className="min-h-14 flex-1 resize-none rounded-md border border-line bg-surface-2 px-3 py-2 text-sm placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-60"
        />
        {streaming ? (
          <button type="button" onClick={onStop} className={btnSecondary}>Stop</button>
        ) : (
          <button type="submit" disabled={!canSend} className={btnPrimary}>Send</button>
        )}
      </div>
      <p id="assistant-input-help" className={`mt-1.5 text-xs ${tooLong ? "text-danger" : "text-muted"}`}>
        {disabled && disabledReason ? disabledReason : `${text.length}/${MAX_CHARS} characters`}
      </p>
    </form>
  );
}
