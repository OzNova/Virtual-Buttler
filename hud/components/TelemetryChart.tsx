"use client";

import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Point = { t: string; cpu: number; ram: number };

// Polls /api/telemetry (2.5s) and keeps the last 40 points.
export default function TelemetryChart({ api }: { api: string }) {
  const [data, setData] = useState<Point[]>([]);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch(`${api}/api/telemetry`, { cache: "no-store" });
        const j = await r.json();
        const t = j.telemetry;
        if (!alive || !t) return;
        const now = new Date().toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
        setData((d) => [...d.slice(-39), { t: now, cpu: t.cpu ?? 0, ram: t.ram_percent ?? 0 }]);
      } catch {
        /* offline */
      }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [api]);

  return (
    <div className="h-44 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
          <CartesianGrid stroke="#d2d2d7" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="t" tick={{ fontSize: 10, fill: "#6e6e73" }} tickLine={false} axisLine={false} minTickGap={32} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "#6e6e73" }} tickLine={false} axisLine={false} />
          <Tooltip />
          <Line type="monotone" dataKey="cpu" stroke="#0071e3" strokeWidth={2} dot={false} name="CPU %" />
          <Line type="monotone" dataKey="ram" stroke="#6e6e73" strokeWidth={2} dot={false} name="RAM %" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
