// frontend/src/components/WizardAI.jsx
import React from "react";
import { chatStart, chatMessage } from "../lib/api";

// ---------- small helpers ----------
function buildMessageFromIntent(i) {
  const parts = [];
  if (i.budget) parts.push(`budget ${Math.round(i.budget)} dollars`);
  if (i.os) parts.push(i.os);
  if (i.prefer_small === true) parts.push("compact phone");
  if (i.prefer_large === true) parts.push("larger screen");
  if (i.min_battery) parts.push(`${i.min_battery} mAh battery`);
  if (i.must_have.length) parts.push(`must have ${i.must_have.join(", ")}`);
  if (i.brands.length) parts.push(`like ${i.brands.join(", ")}`);
  if (i.avoid_brands.length) parts.push(`avoid ${i.avoid_brands.join(", ")}`);
  if (i.min_ram) parts.push(`${i.min_ram} GB RAM`);
  if (i.min_storage) parts.push(`${i.min_storage} GB storage`);
  if (i.camera_priority === true) parts.push("camera priority");
  parts.push("show results"); // nudge backend to answer now
  return parts.join(", ");
}

function Chip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1 rounded-full border text-sm ${
        active ? "bg-black text-white border-black" : "bg-white hover:bg-gray-50 border-gray-300"
      }`}
    >
      {children}
    </button>
  );
}

function Section({ title, children }) {
  return (
    <div className="mb-6">
      <div className="text-sm font-medium text-gray-600 mb-2">{title}</div>
      {children}
    </div>
  );
}

// ---------- main ----------
export default function WizardAI() {
  const [mode, setMode] = React.useState("guided"); // guided | describe
  const [session, setSession] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  // local intent state (never resets unless user hits "Start over")
  const [intent, setIntent] = React.useState({
    budget: 700,
    os: null, // 'Android' | 'iOS'
    prefer_small: null,
    prefer_large: null,
    min_battery: null,
    must_have: [],
    brands: [],
    avoid_brands: [],
    min_ram: null,
    min_storage: null,
    camera_priority: null,
  });

  const steps = [
    { key: "budget", label: "What's your budget?", render: StepBudget },
    { key: "os", label: "Android or iOS — or no preference?", render: StepOS },
    { key: "size", label: "Screen size preference?", render: StepSize },
    { key: "battery", label: "Battery preference?", render: StepBattery },
    { key: "features", label: "Any must-have features?", render: StepFeatures },
    { key: "brands", label: "Any brands you like or want to avoid?", render: StepBrands },
    { key: "ram", label: "Minimum RAM?", render: StepRAM },
    { key: "storage", label: "Minimum storage?", render: StepStorage },
    { key: "camera", label: "Is camera quality a priority?", render: StepCamera },
    { key: "review", label: "Review & find phones", render: StepReview },
  ];
  const [stepIdx, setStepIdx] = React.useState(0);
  const goNext = () => setStepIdx((i) => Math.min(i + 1, steps.length - 1));
  const goBack = () => setStepIdx((i) => Math.max(i - 1, 0));

  const [picks, setPicks] = React.useState([]);
  const [blurb, setBlurb] = React.useState("");

  const resetAll = () => {
    setIntent({
      budget: 700, os: null, prefer_small: null, prefer_large: null, min_battery: null,
      must_have: [], brands: [], avoid_brands: [], min_ram: null, min_storage: null, camera_priority: null,
    });
    setStepIdx(0);
    setError("");
    setPicks([]);
    setBlurb("");
  };

  async function ensureSession() {
    if (session) return session;
    const s = await chatStart();
    setSession(s);
    return s;
  }

  async function runSearch() {
    try {
      setLoading(true);
      setError("");
      const s = await ensureSession();
      const msg = buildMessageFromIntent(intent);
      const res = await chatMessage(s.session_id, msg);
      setPicks(res?.picks || []);
      setBlurb(res?.ask || "");
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  const Current = steps[stepIdx].render;

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-gray-50">
      <div className="max-w-4xl mx-auto px-4 py-10">
        {/* Mode toggle */}
        <div className="mb-6 flex items-center justify-center gap-2">
          <button
            className={`px-3 py-1 rounded-full text-sm border ${
              mode === "guided" ? "bg-black text-white border-black" : "bg-white border-gray-300"
            }`}
            onClick={() => setMode("guided")}
          >
            Guided
          </button>
          <button
            className={`px-3 py-1 rounded-full text-sm border ${
              mode === "describe" ? "bg-black text-white border-black" : "bg-white border-gray-300"
            }`}
            onClick={() => setMode("describe")}
          >
            Describe
          </button>
        </div>

        {/* Centered card */}
        <div className="mx-auto max-w-2xl bg-white rounded-2xl shadow-sm ring-1 ring-gray-200 p-6">
          {mode === "guided" ? (
            <>
              <div className="text-center mb-6">
                <div className="text-xs text-gray-500">Step {stepIdx + 1} of {steps.length}</div>
                <h1 className="text-xl font-semibold mt-1">{steps[stepIdx].label}</h1>
              </div>

              <Current intent={intent} setIntent={setIntent} />

              <div className="mt-8 flex items-center justify-between">
                <button onClick={goBack} className="text-sm text-gray-600 hover:text-black" disabled={stepIdx === 0}>
                  ← Back
                </button>
                <div className="flex items-center gap-2">
                  {stepIdx < steps.length - 1 && (
                    <button onClick={goNext} className="px-4 py-2 rounded-lg bg-black text-white">
                      Next
                    </button>
                  )}
                  {stepIdx === steps.length - 1 && (
                    <button onClick={runSearch} className="px-4 py-2 rounded-lg bg-black text-white">
                      Show results
                    </button>
                  )}
                </div>
              </div>
            </>
          ) : (
            <DescribePanel
              runSearch={async (text) => {
                setLoading(true); setError("");
                try {
                  const s = await ensureSession();
                  const res = await chatMessage(s.session_id, text + ", show results");
                  setPicks(res?.picks || []); setBlurb(res?.ask || "");
                } catch (e) {
                  setError(e.message || "Error");
                } finally {
                  setLoading(false);
                }
              }}
            />
          )}
        </div>

        {error && <div className="mt-4 text-center text-sm text-red-600">{error}</div>}
        {loading && <div className="mt-6 text-center text-gray-600 text-sm">Thinking…</div>}

        {!!picks.length && (
          <div className="mt-10">
            {blurb && <div className="mb-4 text-gray-800">{blurb}</div>}
            <div className="grid md:grid-cols-3 gap-4">
              {picks.map((p, idx) => (
                <div key={idx} className="bg-white rounded-xl shadow-sm ring-1 ring-gray-200 p-4">
                  <div className="aspect-video w-full bg-gray-100 rounded-lg mb-3 overflow-hidden flex items-center justify-center">
                    {p.ImageURL ? (
                      <img src={p.ImageURL} alt={`${p.Brand} ${p.Model}`} className="w-full h-full object-cover" />
                    ) : (
                      <span className="text-xs text-gray-400">{p.Brand} {p.Model}</span>
                    )}
                  </div>
                  <div className="font-medium">{p.Brand} {p.Model}</div>
                  <div className="text-xs text-gray-500">{p.OS} • {p.ReleaseYear}</div>
                  <div className="mt-1 font-semibold">
                    {typeof p.PriceUSD === "number" ? `$${Math.round(p.PriceUSD)}` : (p.PriceUSD || "—")}
                  </div>

                  {(p.DisplayInches || p.Battery_mAh || p.RAM_GB || p.Storage_GB) && (
                    <div className="mt-2 text-xs text-gray-600 space-y-1">
                      {p.DisplayInches && <div>• {p.DisplayInches}" display</div>}
                      {p.Battery_mAh && <div>• {p.Battery_mAh} mAh</div>}
                      {p.RAM_GB && <div>• {p.RAM_GB} GB RAM</div>}
                      {p.Storage_GB && <div>• {p.Storage_GB} GB</div>}
                    </div>
                  )}

                  {(p.Pros?.length || p.Cons?.length) && (
                    <div className="mt-3 grid grid-cols-2 gap-3">
                      {p.Pros?.length > 0 && (
                        <div>
                          <div className="text-xs font-semibold">Pros</div>
                          <ul className="mt-1 space-y-1 text-xs text-gray-700 list-disc ml-4">
                            {p.Pros.slice(0,4).map((t,i)=><li key={i}>{t}</li>)}
                          </ul>
                        </div>
                      )}
                      {p.Cons?.length > 0 && (
                        <div>
                          <div className="text-xs font-semibold">Cons</div>
                          <ul className="mt-1 space-y-1 text-xs text-gray-700 list-disc ml-4">
                            {p.Cons.slice(0,3).map((t,i)=><li key={i}>{t}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-6 flex items-center justify-center gap-3">
              <button onClick={resetAll} className="px-3 py-2 rounded-lg border border-gray-300">
                Start over
              </button>
              <button onClick={() => setMode("guided")} className="px-3 py-2 rounded-lg bg-black text-white">
                Refine answers
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- step renderers ----------
function StepBudget({ intent, setIntent }) {
  return (
    <Section title="Budget">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-gray-700">Drag to set a rough max.</div>
        <div className="text-sm font-medium">${Math.round(intent.budget ?? 700)}</div>
      </div>
      <input
        type="range"
        min={150}
        max={2000}
        step={25}
        value={intent.budget ?? 700}
        onChange={(e) => setIntent((s) => ({ ...s, budget: Number(e.target.value) }))}
        className="w-full accent-black"
      />
    </Section>
  );
}
function StepOS({ intent, setIntent }) {
  return (
    <Section title="System">
      <div className="flex gap-2 flex-wrap">
        <Chip active={intent.os === null} onClick={() => setIntent((s) => ({ ...s, os: null }))}>No preference</Chip>
        <Chip active={intent.os === "Android"} onClick={() => setIntent((s) => ({ ...s, os: "Android" }))}>Android</Chip>
        <Chip active={intent.os === "iOS"} onClick={() => setIntent((s) => ({ ...s, os: "iOS" }))}>iOS</Chip>
      </div>
    </Section>
  );
}
function StepSize({ intent, setIntent }) {
  const setSmall = () => setIntent((s) => ({ ...s, prefer_small: true, prefer_large: false }));
  const setLarge = () => setIntent((s) => ({ ...s, prefer_small: false, prefer_large: true }));
  const setNone = () => setIntent((s) => ({ ...s, prefer_small: null, prefer_large: null }));
  return (
    <Section title="Screen size">
      <div className="flex gap-2 flex-wrap">
        <Chip active={intent.prefer_small === null && intent.prefer_large === null} onClick={setNone}>No preference</Chip>
        <Chip active={intent.prefer_small === true} onClick={setSmall}>Compact</Chip>
        <Chip active={intent.prefer_large === true} onClick={setLarge}>Larger</Chip>
      </div>
    </Section>
  );
}
function StepBattery({ intent, setIntent }) {
  const setNone = () => setIntent((s) => ({ ...s, min_battery: null }));
  const setLong = () => setIntent((s) => ({ ...s, min_battery: 5000 }));
  return (
    <Section title="Battery">
      <div className="flex gap-2 flex-wrap">
        <Chip active={intent.min_battery === null} onClick={setNone}>No preference</Chip>
        <Chip active={intent.min_battery === 5000} onClick={setLong}>Long battery</Chip>
      </div>
    </Section>
  );
}
function StepFeatures({ intent, setIntent }) {
  const opts = ["5G", "Wireless charging", "IP68", "eSIM"];
  const toggle = (x) =>
    setIntent((s) => {
      const has = s.must_have.includes(x.toLowerCase());
      const next = has ? s.must_have.filter((t) => t !== x.toLowerCase()) : [...s.must_have, x.toLowerCase()];
      return { ...s, must_have: next };
    });
  return (
    <Section title="Must-have features">
      <div className="flex gap-2 flex-wrap">
        {opts.map((x) => (
          <Chip key={x} active={intent.must_have.includes(x.toLowerCase())} onClick={() => toggle(x)}>
            {x}
          </Chip>
        ))}
      </div>
    </Section>
  );
}
function StepBrands({ intent, setIntent }) {
  const brands = ["Apple","Samsung","Google","OnePlus","Xiaomi","Sony","Motorola","Nothing","Asus","Oppo","Vivo","Realme","Honor"];
  const toggleLike = (b) =>
    setIntent((s) => {
      const has = s.brands.includes(b);
      return { ...s, brands: has ? s.brands.filter((x) => x !== b) : [...s.brands, b] };
    });
  const toggleAvoid = (b) =>
    setIntent((s) => {
      const has = s.avoid_brands.includes(b);
      return { ...s, avoid_brands: has ? s.avoid_brands.filter((x) => x !== b) : [...s.avoid_brands, b] };
    });

  return (
    <>
      <Section title="Liked brands (optional)">
        <div className="flex gap-2 flex-wrap">
          {brands.map((b) => (
            <Chip key={b} active={intent.brands.includes(b)} onClick={() => toggleLike(b)}>{b}</Chip>
          ))}
        </div>
      </Section>
      <Section title="Avoid brands (optional)">
        <div className="flex gap-2 flex-wrap">
          {brands.map((b) => (
            <Chip key={b} active={intent.avoid_brands.includes(b)} onClick={() => toggleAvoid(b)}>{b}</Chip>
          ))}
        </div>
      </Section>
    </>
  );
}
function StepRAM({ intent, setIntent }) {
  const opts = [null, 6, 8, 12];
  return (
    <Section title="Minimum RAM">
      <div className="flex gap-2 flex-wrap">
        {opts.map((v, i) => (
          <Chip key={i} active={intent.min_ram === v} onClick={() => setIntent((s) => ({ ...s, min_ram: v }))}>
            {v === null ? "No preference" : `${v} GB`}
          </Chip>
        ))}
      </div>
    </Section>
  );
}
function StepStorage({ intent, setIntent }) {
  const opts = [null, 128, 256, 512];
  return (
    <Section title="Minimum storage">
      <div className="flex gap-2 flex-wrap">
        {opts.map((v, i) => (
          <Chip key={i} active={intent.min_storage === v} onClick={() => setIntent((s) => ({ ...s, min_storage: v }))}>
            {v === null ? "No preference" : `${v} GB`}
          </Chip>
        ))}
      </div>
    </Section>
  );
}
function StepCamera({ intent, setIntent }) {
  return (
    <Section title="Camera priority">
      <div className="flex gap-2">
        <Chip active={intent.camera_priority === null} onClick={() => setIntent((s)=>({ ...s, camera_priority: null }))}>No preference</Chip>
        <Chip active={intent.camera_priority === true} onClick={() => setIntent((s)=>({ ...s, camera_priority: true }))}>Yes</Chip>
        <Chip active={intent.camera_priority === false} onClick={() => setIntent((s)=>({ ...s, camera_priority: false }))}>No</Chip>
      </div>
    </Section>
  );
}
function StepReview({ intent }) {
  const rows = [
    ["Budget", intent.budget ? `$${Math.round(intent.budget)}` : "—"],
    ["OS", intent.os || "—"],
    ["Size", intent.prefer_small ? "Compact" : intent.prefer_large ? "Larger" : "—"],
    ["Battery", intent.min_battery ? `${intent.min_battery} mAh` : "—"],
    ["Features", intent.must_have.length ? intent.must_have.join(", ") : "—"],
    ["Like", intent.brands.length ? intent.brands.join(", ") : "—"],
    ["Avoid", intent.avoid_brands.length ? intent.avoid_brands.join(", ") : "—"],
    ["RAM", intent.min_ram ? `${intent.min_ram} GB` : "—"],
    ["Storage", intent.min_storage ? `${intent.min_storage} GB` : "—"],
    ["Camera priority", intent.camera_priority === true ? "Yes" : intent.camera_priority === false ? "No" : "—"],
  ];
  return (
    <div className="text-sm">
      <div className="mb-4 text-gray-700">Looks good? Hit “Show results”. You can always go back and tweak.</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {rows.map(([k, v]) => (
          <React.Fragment key={k}>
            <div className="text-gray-500">{k}</div>
            <div className="font-medium">{v}</div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function DescribePanel({ runSearch }) {
  const [text, setText] = React.useState("");
  return (
    <div>
      <div className="text-gray-700 text-sm mb-3">
        Tell me everything in one go (e.g., “Android, compact, under $800, long battery, avoid Apple”).
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        className="w-full rounded-xl border border-gray-300 p-3 focus:outline-none focus:ring-2 focus:ring-black"
        placeholder="Type here…"
      />
      <div className="mt-4 flex justify-end">
        <button onClick={() => runSearch(text)} className="px-4 py-2 rounded-lg bg-black text-white">
          Show results
        </button>
      </div>
    </div>
  );
}
