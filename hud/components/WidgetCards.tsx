"use client";

import { motion } from "framer-motion";
import type { Widget } from "../lib/api";

// Contextual HUD card: renders whatever widget the agent returned.
// Quiet Apple card — no glow, physics-light spring only.
export default function WidgetCards({ widget }: { widget?: Widget | null }) {
  if (!widget) return null;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 28 }}
      className="rounded-card border border-hairline bg-white p-4 shadow-sm dark:bg-[#1d1d1f]"
    >
      <p className="text-[11px] font-semibold uppercase tracking-wider text-secondary">Context</p>
      {widget.kind === "shopping" && (
        <div className="mt-1 text-sm">
          <p className="font-medium">
            {widget.platform} · {widget.query}
          </p>
          {widget.url && (
            <a className="text-accent underline" href={String(widget.url)} target="_blank" rel="noreferrer">
              Open results
            </a>
          )}
        </div>
      )}
      {widget.kind === "calendar" && (
        <ul className="mt-1 space-y-1 text-sm">
          {(widget.events ?? []).map((e, i) => (
            <li key={i}>
              <span className="font-medium">{e.title}</span>
              {e.start && <span className="text-secondary"> · {new Date(e.start).toLocaleString()}</span>}
            </li>
          ))}
        </ul>
      )}
      {widget.kind === "focus" && (
        <p className="mt-1 text-sm">{widget.suggest ? "Focus block starting soon — enable Focus mode?" : "No focus block starting soon."}</p>
      )}
      {["telemetry", "video", "images", "docs", "vision", "home", "memory"].includes(widget.kind) && (
        <pre className="mt-1 max-h-40 overflow-auto text-xs text-secondary">{JSON.stringify(widget, null, 2)}</pre>
      )}
    </motion.div>
  );
}
