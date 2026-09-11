// Local-only backend helpers. No auth by design (loopback :8000).
export const API = process.env.BUTLER_API || "http://127.0.0.1:8000";
export const WS_BASE = API.replace(/^http/, "ws");

export type Widget =
  | { kind: "telemetry"; telemetry?: unknown }
  | { kind: "shopping"; platform?: string; query?: string; url?: string }
  | { kind: "video"; query?: string }
  | { kind: "images"; query?: string }
  | { kind: "docs"; query?: string; path?: string }
  | { kind: "calendar"; events?: { title: string; start?: string }[] }
  | { kind: "focus"; suggest?: boolean }
  | { kind: "home"; entity_id?: string }
  | { kind: string; [k: string]: unknown };

export async function postAgent(message: string) {
  const r = await fetch(`${API}/api/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!r.ok) throw new Error(`agent ${r.status}`);
  return r.json() as Promise<{ message: string; widget?: Widget; call?: unknown }>;
}

export async function hudState() {
  const r = await fetch(`${API}/api/hud/state`, { cache: "no-store" });
  if (!r.ok) throw new Error(`hud ${r.status}`);
  return r.json();
}

export function chatSocket(onToken: (t: string) => void, onResult: (m: unknown) => void) {
  const ws = new WebSocket(`${WS_BASE}/ws/chat`);
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === "token") onToken(data.text);
      else if (data.type === "result") onResult(data);
    } catch {
      /* ignore */
    }
  };
  return ws;
}

export function audioSocket(onLevel: (level: number, speaking: boolean) => void) {
  const ws = new WebSocket(`${WS_BASE}/ws/audio`);
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === "level") onLevel(data.level ?? 0, !!data.speaking);
    } catch {
      /* ignore */
    }
  };
  return ws;
}
