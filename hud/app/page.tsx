"use client";

import { Canvas } from "@react-three/fiber";
import { useEffect, useState } from "react";
import CommandBar from "../components/CommandBar";
import Orb from "../components/Orb";
import TelemetryChart from "../components/TelemetryChart";
import WidgetCards from "../components/WidgetCards";
import { API, audioSocket, postAgent, type Widget } from "../lib/api";

type Msg = { role: "you" | "butler"; text: string };

export default function Home() {
  const [msgs, setMsgs] = useState<Msg[]>([{ role: "butler", text: "Butler HUD ready. Backend: :8000 (local-only)." }]);
  const [widget, setWidget] = useState<Widget | null>(null);
  const [level, setLevel] = useState(0.2);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  async function quickAction(label: string) {
    setMsgs((m) => [...m.slice(-49), { role: "you", text: label }]);
    setBusyAction(label);
    try {
      const res = await postAgent(label);
      setMsgs((m) => [...m.slice(-49), { role: "butler", text: res.message }]);
      if (res.widget) setWidget(res.widget);
    } catch {
      setMsgs((m) => [...m.slice(-49), { role: "butler", text: "Could not reach Butler on :8000." }]);
    } finally {
      setBusyAction(null);
    }
  }

  useEffect(() => {
    const ws = audioSocket((lv) => setLevel(lv));
    return () => ws.close();
  }, []);

  return (
    <main className="mx-auto grid min-h-screen max-w-6xl grid-cols-1 gap-4 p-4 md:grid-cols-[280px_1fr_280px]">
      <section className="rounded-card border border-hairline bg-white p-4 dark:bg-[#1d1d1f]">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-secondary">Status</h2>
        <div className="mt-2 h-40">
          <Canvas camera={{ position: [0, 0, 3.2] }}>
            <ambientLight intensity={1.1} />
            <directionalLight position={[2, 3, 4]} intensity={0.8} />
            <Orb level={level} />
          </Canvas>
        </div>
        <div className="mt-2">
          <TelemetryChart api={API} />
        </div>
      </section>

      <section className="flex min-h-[70vh] flex-col rounded-card border border-hairline bg-white p-4 dark:bg-[#1d1d1f]">
        <div className="flex-1 space-y-2 overflow-y-auto" aria-live="polite">
          {msgs.map((m, i) => (
            <div key={i} className={m.role === "you" ? "text-right" : "text-left"}>
              <span
                className={
                  m.role === "you"
                    ? "inline-block max-w-[75%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-left text-[15px] text-white"
                    : "inline-block max-w-[75%] rounded-2xl rounded-bl-md bg-canvas px-3.5 py-2 text-left text-[15px] dark:bg-black"
                }
              >
                {m.text}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 space-y-3">
          <WidgetCards widget={widget} />
          <CommandBar
            onResult={(message, w) => {
              setMsgs((m) => [...m.slice(-49), { role: "butler", text: message }]);
              if (w) setWidget(w);
            }}
          />
        </div>
      </section>

      <section className="rounded-card border border-hairline bg-white p-4 dark:bg-[#1d1d1f]">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-secondary">Actions</h2>
        <div className="mt-2 grid grid-cols-2 gap-2">
          {["System Check", "Screenshot", "Time", "News", "Bitcoin", "Dollar"].map((label) => (
            <button
              key={label}
              onClick={() => quickAction(label)}
              disabled={busyAction !== null}
              className="rounded-xl border border-hairline px-3 py-2.5 text-[13px] font-medium hover:bg-canvas active:scale-[0.98]"
            >
              {label}
            </button>
          ))}
        </div>
        <p className="mt-3 text-xs text-secondary">Local-only · FastAPI :8000 · Tauri tray + ⌘⇧Space</p>
      </section>
    </main>
  );
}
