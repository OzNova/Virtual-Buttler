"use client";

import { useState } from "react";
import { postAgent, type Widget } from "../lib/api";

export default function CommandBar({ onResult }: { onResult: (message: string, widget?: Widget) => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    const text = value.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const res = await postAgent(text);
      onResult(res.message, res.widget);
      setValue("");
    } catch {
      onResult("Could not reach Butler on :8000. Is `python -m server.main` running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2 rounded-2xl border border-hairline bg-canvas p-1.5 focus-within:border-accent">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && send()}
        placeholder="Ask Butler to do something…"
        aria-label="Command input"
        className="min-w-0 flex-1 bg-transparent px-3 py-2 text-[15px] outline-none placeholder:text-secondary/60"
      />
      <button
        onClick={send}
        disabled={busy}
        className="h-9 shrink-0 rounded-xl bg-accent px-5 text-sm font-semibold text-white hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
      >
        {busy ? "…" : "Send"}
      </button>
    </div>
  );
}
