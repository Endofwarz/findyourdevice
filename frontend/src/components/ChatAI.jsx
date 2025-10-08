// frontend/src/components/ChatAI.jsx
import React, { useEffect, useRef, useState } from "react";
import { chatStart, chatMessage, health } from "../lib/api";

export default function ChatAI() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]); // {role:'assistant'|'user', text:string}
  const [input, setInput] = useState("");
  const [picks, setPicks] = useState([]);       // latest picks (array)
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const scrollerRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const h = await health(); // optional sanity check
        // console.log("backend:", h);
      } catch (e) {
        console.error(e);
      }
      const s = await chatStart();
      setSessionId(s.session_id);
      setMessages([{ role: "assistant", text: s.message }]);
    })();
  }, []);

  useEffect(() => {
    // auto-scroll to bottom on new messages
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [messages, picks]);

  async function send(msgText) {
    if (!sessionId || !msgText.trim()) return;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text: msgText }]);
    setInput("");

    try {
      const resp = await chatMessage(sessionId, msgText);
      setCount(resp.count ?? 0);
      setPicks(Array.isArray(resp.picks) ? resp.picks : []);

      // Prefer the follow-up question if present; otherwise summarize picks
      if (resp.ask) {
        setMessages((m) => [...m, { role: "assistant", text: resp.ask }]);
      } else if (resp.picks && resp.picks.length) {
const [first] = resp.picks;
const blurb = first
  ? `Nice! Based on what you told me, I’d start with **${first.Brand} ${first.Model}**. I’ve also added two close alternatives below. (${resp.count} phones match your vibe.)`
  : `Here are ${resp.picks.length} solid options I like. (${resp.count} candidates in range.)`;
setMessages((m) => [...m, { role: "assistant", text: blurb }]);
      } else {
        setMessages((m) => [
          ...m,
          {
            role: "assistant",
            text:
              "I couldn't find matches yet. Try adding a budget, OS (Android/iOS), and a must-have (e.g., wireless charging). You can also type “show results”.",
          },
        ]);
      }
    } catch (e) {
      console.error(e);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: `⚠️ Error: ${String(e.message || e)}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    send(input);
  }

  return (
    <div style={styles.wrap}>
      <h2 style={{ margin: 0 }}>Ask AI (phone picker)</h2>
      <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>
        Type natural language like: <em>“under 700, Android, wireless charging, 5000mAh, 8GB RAM”</em>
      </div>

      <div ref={scrollerRef} style={styles.chat}>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              ...styles.bubble,
              ...(m.role === "assistant" ? styles.assist : styles.user),
            }}
          >
            <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 2 }}>
              {m.role === "assistant" ? "Assistant" : "You"}
            </div>
            <div>{m.text}</div>
          </div>
        ))}

        {picks?.length ? (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>
              Top picks ({picks.length}) — candidates in scope: {count}
            </div>
            <div style={styles.grid}>
              {picks.map((p, i) => (
                <div key={`${p.Slug || i}`} style={styles.card}>
                  <div style={{ fontWeight: 700 }}>
                    {p.Brand} {p.Model}
                  </div>
                  <div style={{ fontSize: 12, opacity: 0.8 }}>
                    {p.ReleaseYear} · {p.OS}
                  </div>
                  <div style={styles.specs}>
                    <Spec label="Display" val={`${p.DisplayInches ?? "?"}"`} />
                    <Spec label="Battery" val={`${p.Battery_mAh ?? "?"} mAh`} />
                    <Spec label="RAM" val={`${p.RAM_GB ?? "?"} GB`} />
                    <Spec label="Storage" val={`${p.Storage_GB ?? "?"} GB`} />
                    <Spec label="Camera" val={`${p.MainCameraMP ?? "?"} MP`} />
                    <Spec
                      label="Weight"
                      val={p.Weight_g ? `${p.Weight_g} g` : "?"}
                    />
                    <Spec
                      label="Price"
                      val={p.PriceUSD ? `$${p.PriceUSD}` : "—"}
                    />
                  </div>
                  {p.NotableFeatures ? (
                    <div style={styles.tagsWrap}>
                      {String(p.NotableFeatures)
                        .split(/[;,]/)
                        .map((t) => t.trim())
                        .filter(Boolean)
                        .slice(0, 6)
                        .map((t, j) => (
                          <span key={j} style={styles.tag}>
                            {t}
                          </span>
                        ))}
                    </div>
                  ) : null}
                  {p.Slug ? (
                    <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
                      slug: <code>{p.Slug}</code>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <form onSubmit={onSubmit} style={styles.row}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={busy ? "Working..." : "Type your message"}
          disabled={busy || !sessionId}
          style={styles.input}
        />
        <button disabled={busy || !sessionId} style={styles.btn}>
          Send
        </button>
        <button
          type="button"
          onClick={() => send("show results")}
          disabled={busy || !sessionId}
          style={{ ...styles.btn, marginLeft: 8 }}
          title="Force recommendations with current info"
        >
          Show results
        </button>
      </form>
    </div>
  );
}

function Spec({ label, val }) {
  return (
    <div style={{ marginRight: 10, marginBottom: 4 }}>
      <span style={{ opacity: 0.7 }}>{label}:</span> {val}
    </div>
  );
}

const styles = {
  wrap: {
    maxWidth: 960,
    margin: "24px auto",
    padding: 16,
    border: "1px solid #ddd",
    borderRadius: 12,
  },
  chat: {
    height: 420,
    overflowY: "auto",
    background: "#fafafa",
    padding: 12,
    border: "1px solid #eee",
    borderRadius: 8,
  },
  bubble: {
    padding: 10,
    borderRadius: 10,
    marginBottom: 10,
    maxWidth: "80%",
    whiteSpace: "pre-wrap",
  },
  assist: { background: "#fff", border: "1px solid #eee" },
  user: { background: "#e8f0ff", marginLeft: "auto" },
  row: { display: "flex", marginTop: 12 },
  input: {
    flex: 1,
    padding: "10px 12px",
    border: "1px solid #ccc",
    borderRadius: 8,
    outline: "none",
  },
  btn: {
    padding: "10px 14px",
    border: "1px solid #333",
    background: "#111",
    color: "#fff",
    borderRadius: 8,
    cursor: "pointer",
    marginLeft: 8,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
    gap: 12,
  },
  card: {
    background: "#fff",
    border: "1px solid #eee",
    borderRadius: 10,
    padding: 12,
  },
  specs: {
    display: "flex",
    flexWrap: "wrap",
    marginTop: 6,
    fontSize: 13,
  },
  tagsWrap: { marginTop: 6 },
  tag: {
    display: "inline-block",
    background: "#eef3ff",
    border: "1px solid #dbe3ff",
    padding: "2px 6px",
    borderRadius: 8,
    fontSize: 12,
    marginRight: 6,
    marginBottom: 6,
  },
};
