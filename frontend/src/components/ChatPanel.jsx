import { useEffect, useRef, useState } from "react";
import ChatInput from "./ChatInput";
import { PrimaryCard, AltCard } from "./ResultCards";

const API = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export default function ChatPanel({ mode }) {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [ask, setAsk] = useState(null);
  const [picks, setPicks] = useState([]);
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);
  const firstDescribeRef = useRef(true);

  async function start() {
    // start server session but DO NOT show its initial message
    const r = await fetch(`${API}/chat/start`, { method: "POST" });
    const j = await r.json();
    setSession(j.session_id);
    setAsk(null);
    setMessages([]);          // <-- no assistant bubble at start
    setPicks([]); setCount(0);
    firstDescribeRef.current = true;
  }

  useEffect(() => { start(); }, []);
  useEffect(() => { start(); }, [mode]); // restart when switching tabs

  function push(role, text) {
    setMessages((m) => [...m, { role, text }]);
  }

  async function send(userText) {
    if (!session) return;
    setBusy(true);
    push("user", userText);
    try {
      const r = await fetch(`${API}/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session, message: userText })
      });
      const j = await r.json();

      // If Describe mode & first message produced a follow-up question, auto-request results once.
      if (
        mode === "Describe" &&
        firstDescribeRef.current &&
        (!Array.isArray(j.picks) || j.picks.length === 0) &&
        j.ask
      ) {
        firstDescribeRef.current = false; // prevent loops
        // silently ask for results so the user sees picks quickly
        const r2 = await fetch(`${API}/chat/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: session, message: "show results" })
        });
        const j2 = await r2.json();
        if (j2.ask) push("assistant", j2.ask);
        setAsk(j2.ask || null);
        setPicks(Array.isArray(j2.picks) ? j2.picks : []);
        setCount(j2.count || 0);
      } else {
        if (j.ask) push("assistant", j.ask);
        setAsk(j.ask || null);
        setPicks(Array.isArray(j.picks) ? j.picks : []);
        setCount(j.count || 0);
        firstDescribeRef.current = false;
      }
    } catch {
      push("assistant", "Oops — I couldn’t reach the server. Try again.");
    } finally {
      setBusy(false);
      setTimeout(() => scrollRef.current?.scrollTo({ top: 999999, behavior: "smooth" }), 100);
    }
  }

  const primary = picks[0], alt1 = picks[1], alt2 = picks[2];
  const banner = mode === "Guided"
    ? { text: "Guided mode — I’ll ask quick questions.", cls: "bg-blue-50 text-blue-900 border-blue-100" }
    : { text: "Describe mode — tell me everything in one go.", cls: "bg-violet-50 text-violet-900 border-violet-100" };

  return (
    <div className="grid grid-cols-3 gap-6">
      {/* Chat column */}
      <div className="col-span-1 bg-white rounded-3xl p-5 shadow-soft border flex flex-col h-[80vh]">
        <div className={`rounded-2xl px-3 py-2 mb-3 text-sm border ${banner.cls}`}>{banner.text}</div>

        <div ref={scrollRef} className="flex-1 overflow-auto space-y-3 pr-2">
          {messages.map((m, i) => (
            <div key={i} className={m.role === "assistant" ? "text-slate-900" : "text-blue-700"}>
              <div className={m.role === "assistant" ? "bg-slate-100 rounded-2xl px-3 py-2 inline-block" : "bg-blue-50 rounded-2xl px-3 py-2 inline-block"}>
                {m.text}
              </div>
            </div>
          ))}
        </div>

        <div className="pt-3 border-t">
          <ChatInput mode={mode} lastAsk={ask} onSend={send} disabled={busy}/>
          <div className="text-xs text-slate-500 mt-2">Matching phones: {count ?? 0}</div>
        </div>
      </div>

      {/* Results column */}
      <div className="col-span-2 space-y-4">
        {primary ? (
          <div className="grid grid-cols-3 gap-4">
            <PrimaryCard p={primary} blurb={ask}/>
            {alt1 && <AltCard p={alt1} blurb={null}/>}
            {alt2 && <AltCard p={alt2} blurb={null}/>}
          </div>
        ) : (
          <div className="rounded-3xl p-10 text-slate-500 bg-white shadow-inner border h-[80vh] flex items-center justify-center text-center">
            In {mode.toLowerCase()} mode, I’ll show suggestions here as soon as I can.
          </div>
        )}
      </div>
    </div>
  );
}
