// frontend/src/lib/api.js
const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function j(r) {
  if (!r.ok) {
    const t = await r.text().catch(() => `${r.status} ${r.statusText}`);
    throw new Error(t || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

export async function health() {
  return j(await fetch(`${BASE}/health`));
}

export async function chatStart() {
  return j(await fetch(`${BASE}/chat/start`, { method: "POST" }));
}

export async function chatMessage(session_id, message) {
  return j(
    await fetch(`${BASE}/chat/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, message }),
    })
  );
}
