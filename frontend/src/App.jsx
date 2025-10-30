import React, { useEffect, useState } from "react";
import TopNav from "./components/TopNav.jsx";
import { AnimatePresence, motion } from "framer-motion";
import { Smartphone, Tablet, Laptop, Headphones } from "lucide-react";
import { Sparkles, SlidersHorizontal, MessageSquareText, Lock } from "lucide-react";



/* ------------------------- theme ------------------------- */
const theme = {
  brand: "indigo",
  pillOn: "bg-indigo-600 text-white border-indigo-600",
  pillOff: "bg-white hover:bg-indigo-50 border-indigo-200",
};

/* ------------------------- API base ------------------------- */
/**
 * We require VITE_API_BASE in production (Vercel).
 * Example value (no trailing slash):
 *   https://your-backend.onrender.com
 */
function resolveApiBase() {
  const env = (import.meta.env?.VITE_API_BASE || "").trim();
  if (env) return env.replace(/\/+$/, ""); // strip trailing slash

  // Local dev fallback
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    return "http://127.0.0.1:8000";
  }

  // If we got here in production, the env var isn't set.
  // Throw a clear error so the UI shows a helpful message.
  throw new Error(
    "Missing VITE_API_BASE. Set it in Vercel → Settings → Environment Variables to your FastAPI base URL (https)."
  );
}

let API;
try {
  API = resolveApiBase();
  console.log("[API] Using base:", API);
} catch (e) {
  // surface a readable error once on load
  alert(e.message || String(e));
  // make API something harmless so later fetches don't try same-origin
  API = "http://127.0.0.1:8000";
}


/* ------------------------- tiny fetch helpers ------------------------- */
async function j(url, init) {
  try {
    const r = await fetch(url, init);
    const text = await r.text(); // always read text first
    if (!r.ok) {
      const msg = text?.slice(0, 800) || `${r.status} ${r.statusText}`;
      throw new Error(msg);
    }
    // try parse JSON, but don’t crash the UI if it isn’t JSON
    try { return JSON.parse(text); } catch { throw new Error(text || "Invalid JSON"); }
  } catch (e) {
    // surface to the UI
    console.error("API error:", e?.message || e);
    throw e;
  }
}

async function startChat() {
  return j(`${API}/chat/start`, { method: "POST" });
}
async function msgChat(session_id, message) {
  return j(`${API}/chat/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, message }),
  });
}
async function patchChat(session_id, patch) {
  return j(`${API}/chat/patch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, patch }),
  });
}

function retailerLabel(id) {
  if (!id) return "retailer";
  const m = String(id).toLowerCase();
  if (m === "ebay") return "eBay";
  if (m === "amazon") return "Amazon";
  if (m === "bestbuy") return "Best Buy";
  return id.charAt(0).toUpperCase() + id.slice(1);
}

/* format 1234.5 -> "1 234.50" (locale-friendly) */
function formatMoney(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v ?? "");
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ---------- Amazon affiliate helpers (no PA-API needed) ---------- */
const MARKET_DOMAINS = {
  se: "https://www.amazon.se",
  de: "https://www.amazon.de",
  uk: "https://www.amazon.co.uk",
  us: "https://www.amazon.com",
};

/**
 * Reads affiliate setup from env:
 *   VITE_AMZ_MARKET      -> se | de | uk | us  (default: se)
 *   VITE_AMZ_TAG         -> fallback tag (e.g., findyourdevic-21)
 *   VITE_AMZ_TAG_SE/DE/UK/US -> market-specific overrides (optional)
 */
function readAffiliateConfig() {
  const market = (import.meta.env?.VITE_AMZ_MARKET || "se").toLowerCase();
  const domain = MARKET_DOMAINS[market] || MARKET_DOMAINS.se;

  const key = "VITE_AMZ_TAG_" + market.toUpperCase();
  const tag = (import.meta.env?.[key] || import.meta.env?.VITE_AMZ_TAG || "").trim();

  return { market, domain, tag };
}

/** Build a search URL like:
 *   https://www.amazon.se/s?k=Apple+iPhone+16+Pro+Max&tag=findyourdevic-21
 */
function amazonAffiliateSearchUrl(pick) {
  const { domain, tag } = readAffiliateConfig();
  const q = [pick?.Brand, pick?.Model].filter(Boolean).join(" ");
  const base = `${domain}/s?k=${encodeURIComponent(q)}`;
  return tag ? `${base}&tag=${encodeURIComponent(tag)}` : base;
}

/* ---- Marketplaces: logo + search links ---- */
const LOGOS = {
  amazon: "https://unpkg.com/simple-icons@v13/icons/amazon.svg",
  prisjakt: "https://cdn.filestackcontent.com/auto_image/46NYHSdSXyrgcK0I8aws",
  idealo: "https://upload.wikimedia.org/wikipedia/commons/5/57/Idealo_logo.jpg",
};

function brandModelQuery(brand, model) {
  return encodeURIComponent([brand, model].filter(Boolean).join(" "));
}

function buildMarketplaceLinks(brand, model) {
  const q = brandModelQuery(brand, model);
  return [
    {
      id: "amazon",
      label: "Amazon",
      logo: LOGOS.amazon,
      url: `https://www.amazon.se/s?k=${q}`,
    },
    {
      id: "prisjakt",
      label: "Prisjakt",
      logo: LOGOS.prisjakt,
      url: `https://www.prisjakt.nu/search?search=${q}`,
    },
    {
      id: "idealo",
      label: "idealo",
      logo: LOGOS.idealo,
      url: `https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q=${q}`,
    },
  ];
}




/* ------------------------- session hook ------------------------- */
function useSession() {
  const [sid, setSid] = useState(null);
  const [intent, setIntent] = useState({});
  const [picks, setPicks] = useState(null);
  const [ui, setUi] = useState(null);
  const [messages, setMessages] = useState([]);
  const [thinking, setThinking] = useState(false);
  const [blurb, setBlurb] = useState(null);

  const start = async () => {
    try {
      const res = await startChat();
      setSid(res.session_id);
      setMessages([{ from: "assistant", text: res.message }]);
      setUi(res.ui || null);
      setPicks(null);
      setBlurb(null);
    } catch (e) {
      alert("Failed to start chat:\n" + (e?.message || e));
    }
  };

  const send = async (text) => {
    if (!sid) return;
    setMessages((m) => [...m, { from: "user", text }]);
    try {
      const res = await msgChat(sid, text);
      setUi(res.ui || null);
      setIntent(res.intent || {});
      if (res.picks) setPicks(res.picks);
      if (res.ask)   setBlurb(res.ask);
      if (res.ask)   setMessages((m) => [...m, { from: "assistant", text: res.ask }]);
    } catch (e) {
      setMessages((m) => [...m, { from: "assistant", text: "Sorry—request failed." }]);
      alert("Request failed:\n" + (e?.message || e));
    }
  };

  const patch = async (partial) => {
    if (!sid) return;
    try {
      const res = await patchChat(sid, partial);
      setUi(res.ui || null);
      setIntent(res.intent || {});
      if (res.picks) setPicks(res.picks);
      if (res.ask)   setBlurb(res.ask);
      if (res.ask)   setMessages((m) => [...m, { from: "assistant", text: res.ask }]);
    } catch (e) {
      alert("Update failed:\n" + (e?.message || e));
    }
  };

  return { sid, intent, picks, ui, messages, thinking, setThinking, blurb, start, send, patch };
}





/* ------------------------- steps (we’ll subset for Simple) ------------------------- */
const ALL_STEPS = [
  { key: "budget",       label: "What’s your budget?", type: "budget" },
  { key: "os",           label: "Android or iOS — or no preference?", type: "os" },
  { key: "prefer_small", label: "Screen size preference?", type: "size" },
  { key: "min_battery",  label: "Battery preference?", type: "battery" },
  { key: "must_have",    label: "Any must-have features?", type: "features" },
  { key: "brands",       label: "Any brands you like?", type: "brands" },
  { key: "min_ram",      label: "Minimum RAM?", type: "ram" },
  { key: "min_storage",  label: "Minimum storage?", type: "storage" },
  { key: "camera_priority", label: "Do you care about camera quality?", type: "camera" },
];

/* ------------------------- client explain fallbacks ------------------------- */
function deriveClientExplanation(bullet, isCon = false) {
  const t = String(bullet || "").toLowerCase();
  if (t.includes("battery")) return isCon ? "May drain quicker than expected." : "Longer time between charges.";
  if (t.includes("ram"))     return isCon ? "Less headroom for multitasking." : "Keeps more apps fast and responsive.";
  if (t.includes("storage")) return isCon ? "Might run out of space sooner."   : "More room for photos, apps, and videos.";
  if (t.includes("display") || t.includes("screen")) return "Easier to read and watch videos.";
  if (t.includes("compact"))  return "Smaller and easier to hold.";
  if (t.includes("wireless") && t.includes("charging")) return "Place on a pad—no cable needed.";
  if (t.includes("ip68") || t.includes("water") || t.includes("dust")) return "Better protection from water and dust.";
  if (t.includes("camera") || t.includes("mp")) return "Sharper, clearer photos.";
  if (t.includes("heavy"))    return "Can feel weighty in hand or pocket.";
  if (t.includes("expensive") || t.includes("price")) return "Costs more than similar phones.";
  return isCon ? "Potential drawback to consider." : "Helpful in everyday use.";
}
function findExplanation(pick, bullet, isCon = false) {
  const m = pick?.Explain;
  const key = String(bullet || "").trim().toLowerCase();
  if (m) {
    const dict = isCon ? m.cons : m.pros;
    if (dict) {
      for (const [k, v] of Object.entries(dict)) {
        if (String(k).trim().toLowerCase() === key) return v;
      }
      for (const [k, v] of Object.entries(dict)) {
        const nk = String(k).trim().toLowerCase();
        if (nk.includes(key) || key.includes(nk)) return v;
      }
    }
  }
  return deriveClientExplanation(bullet, isCon);
}

/* =========================================================
   MAIN APP
   ========================================================= */

export default function App() {
  const { sid, intent, picks, messages, thinking, setThinking, blurb, start, send, patch } = useSession();

  // landing -> categories -> mode -> wizard|describe -> results
  const [view, setView] = useState("landing");
  const [steps, setSteps] = useState(ALL_STEPS); // will shrink for Simple mode
  const [stepIdx, setStepIdx] = useState(0);
  const [freeText, setFreeText] = useState("");
  const [describeText, setDescribeText] = useState("");
  const [refineText, setRefineText] = useState("");

  useEffect(() => { start(); }, []);

const finishAndSearch = async () => {
  setThinking(true);
  try {
    await new Promise((r) => setTimeout(r, 300)); // small UX delay only
    await send("show results");
    setView("results");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } finally {
    setThinking(false);
  }
};


  const onNext = async () => {
    if (freeText.trim()) {
      await send(freeText.trim());
      setFreeText("");
    }
    if (stepIdx >= steps.length - 1) {
      await finishAndSearch();
    } else {
      setStepIdx((s) => s + 1);
    }
  };
  const onBack = () => {
    if (stepIdx === 0) return;
    setStepIdx((s) => s - 1);
  };

  const chooseMode = (mode) => {
    if (mode === "simple") {
      setSteps(ALL_STEPS.slice(0, 5)); // ~5 questions
      setStepIdx(0);
      setView("wizard");
    } else if (mode === "extended") {
      setSteps(ALL_STEPS);
      setStepIdx(0);
      setView("wizard");
    } else {
      setDescribeText("");
      setView("describe");
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {/* Top nav ONLY on wizard per your request */}
{(view === "wizard" || view === "results") ? (
  <header className="py-10 bg-gradient-to-b from-indigo-50 to-sky-50">
    <TopNav onHome={() => window.location.reload()} />
  </header>
) : null}

      <main className="mx-auto max-w-4xl px-4 pb-16">
        {/* Landing */}
        {view === "landing" && (
          <Centered>
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-2xl text-center">
              <h2 className="text-3xl md:text-4xl font-semibold tracking-tight">Find your next device — effortlessly</h2>
              <p className="text-slate-600 mt-3">Tell us what matters and we’ll do the rest. Simple, friendly, and private.</p>
              <motion.button
                whileTap={{ scale: 0.98 }}
                className="mt-8 inline-flex items-center gap-2 px-7 py-3 rounded-2xl bg-gradient-to-r from-indigo-600 to-sky-600 text-white text-lg shadow-lg"
                onClick={() => setView("categories")}
              >
                Start
              </motion.button>
            </motion.div>
          </Centered>
        )}

        {/* Categories */}
        {view === "categories" && (
          <Centered>
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-2xl">
              <h3 className="text-center text-2xl font-semibold">What are you shopping for?</h3>
              <div className="grid sm:grid-cols-2 gap-5 mt-8 place-items-center">
                <CategoryCard title="Phones" onClick={() => setView("modes")} />
                <CategoryCard title="Tablets" disabled />
                <CategoryCard title="Laptops" disabled />
                <CategoryCard title="Headphones" disabled />
              </div>
              <p className="text-center text-sm text-slate-500 mt-6">We’ll add more categories soon.</p>
            </motion.div>
          </Centered>
        )}

        {/* Mode selection (Simple / Extended / Describe) */}

{view === "modes" && (
  <div className="min-h-[60vh] flex items-center justify-center">
    <div className="w-full max-w-5xl">
      <h3 className="text-center text-2xl md:text-3xl font-semibold">
        How would you like to proceed?
      </h3>

      <div className="mt-6 grid gap-5 md:grid-cols-3 place-items-center">
        <ModeCard
          variant="simple"
          onClick={() => chooseMode("simple")}
        />
        <ModeCard
          variant="extended"
          onClick={() => chooseMode("extended")}
        />
        <ModeCard
          variant="describe"
          onClick={() => chooseMode("describe")}
        />
      </div>
    </div>
  </div>
)}




        {/* Describe free-form */}
        {view === "describe" && (
          <Centered>
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-2xl">
              <div className="bg-white rounded-3xl shadow p-6 md:p-8">
                <div className="text-center text-xl md:text-2xl font-semibold">Tell us what you’re looking for</div>
                <textarea
                  className="w-full mt-5 rounded-2xl border p-4 min-h-[140px]"
                  placeholder="E.g., I want a compact Android under €600 with great battery and wireless charging."
                  value={describeText}
                  onChange={(e) => setDescribeText(e.target.value)}
                />
                <div className="mt-6 flex items-center justify-end gap-3">
                  <button className="px-4 py-2 rounded-xl border" onClick={() => setView("modes")}>Back</button>
                  <button
                    className="px-5 py-2 rounded-xl bg-black text-white"
                    onClick={async () => {
                      if (!describeText.trim()) return;
                      setThinking(true);
                      await send(describeText.trim());
                      await send("show results");
                      setThinking(false);
                      setView("results");
                    }}
                  >
                    Find phones
                  </button>
                </div>
              </div>
            </motion.div>
          </Centered>
        )}

        {/* Wizard one-at-a-time */}
        {view === "wizard" && (
          <WizardStep
            stepIndex={stepIdx}
            total={steps.length}
            stepDef={steps[stepIdx]}
            intent={intent}
            onPatch={patch}
            onBack={onBack}
            onNext={onNext}
            freeText={freeText}
            setFreeText={setFreeText}
          />
        )}

        {/* Results (featured + runner-ups) + refine box */}
        {view === "results" && (
          <>
            <ResultsView picks={picks} blurb={blurb}  />
            <div className="mt-8 bg-white rounded-3xl shadow p-6">
              <div className="text-lg font-semibold">Not happy with the picks?</div>
              <p className="text-slate-600 text-sm mt-1">
                Tell me more and I’ll refine—your previous answers are remembered.
              </p>
              <div className="mt-4 flex gap-3">
                <input
                  className="flex-1 rounded-2xl border px-3 py-3"
                  placeholder="E.g., I actually prefer iOS, and I can spend up to €900."
                  value={refineText}
                  onChange={(e) => setRefineText(e.target.value)}
onKeyDown={async (e) => {
  if (e.key === "Enter" && refineText.trim()) {
    setThinking(true);
    try {
      await send(refineText.trim());
      await send("show results");
      setRefineText("");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setThinking(false);
    }
  }
}}
                />
                <button
                  className="px-5 py-3 rounded-2xl bg-black text-white"
onClick={async () => {
  if (!refineText.trim()) return;
  setThinking(true);
  try {
    await send(refineText.trim());
    await send("show results");
    setRefineText("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } finally {
    setThinking(false);
  }
}}
                >
                  Refine
                </button>
              </div>
            </div>
          </>
        )}
      </main>

      {/* overlay */}
      <AnimatePresence>{thinking && <SearchingOverlay />}</AnimatePresence>
    </div>
  );
}

/* ========================= UI blocks ========================= */
function Centered({ children }) {
  return (
    <div className="min-h-[68vh] flex items-center justify-center">{children}</div>
  );
}

function CategoryCard({ title, onClick, disabled }) {
  const IconMap = { Phones: Smartphone, Tablets: Tablet, Laptops: Laptop, Headphones: Headphones };
  const Icon = IconMap[title] || Smartphone;
  return (
    <button
      onClick={!disabled ? onClick : undefined}
      className={`relative w-full max-w-xs h-36 rounded-3xl border shadow-sm flex flex-col items-center justify-center text-xl font-medium transition
        ${disabled ? "opacity-60 cursor-not-allowed" : "bg-white hover:shadow-md active:scale-[0.99] border-indigo-200"}`}
    >
      <Icon className="h-9 w-9 text-indigo-600 mb-2" />
      <span className="text-slate-800">{title}</span>
      {disabled && (
        <span className="absolute bottom-3 text-xs px-2 py-1 rounded-full bg-slate-200 text-slate-700">
          Coming soon
        </span>
      )}
    </button>
  );
}

function IconBadge({ Icon }) {
  return (
    <div className="shrink-0 rounded-2xl p-3 bg-indigo-50 text-indigo-700 border border-indigo-200">
      <Icon className="w-6 h-6" />
    </div>
  );
}

function ModeCard({ variant = "simple", onClick, disabled = false }) {
  // one source of truth for copy + icon per variant
  const presets = {
    simple: {
      title: "Simple",
      blurb: "Answer 4–5 quick questions for fast, sensible picks.",
      audience: "quick decisions",
      Icon: Sparkles,
    },
    extended: {
      title: "Extended",
      blurb: "Tune battery, size, storage and camera for a closer match.",
      audience: "power shoppers",
      Icon: SlidersHorizontal,
    },
    describe: {
      title: "Describe",
      blurb: "Type exactly what you want and let the assistant figure it out.",
      audience: "free-form input",
      Icon: MessageSquareText,
    },
  };

  const { title, blurb, audience, Icon } = presets[variant] || presets.simple;

  return (
    <button
      type="button"
      onClick={!disabled ? onClick : undefined}
 className={`w-full max-w-[420px] h-full min-h-[220px] rounded-3xl border p-5 text-left transition
                  flex flex-col justify-between
        ${disabled ? "opacity-40 cursor-not-allowed" : "bg-white hover:shadow-md border-indigo-200"}`}
    >
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center">
          <Icon className="h-5 w-5" />
        </div>
        <div className="text-xl font-semibold">{title}</div>
      </div>

      <div className="mt-2 text-slate-600">{blurb}</div>

      <div className="mt-3 inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 whitespace-nowrap">
        <span>Recommended for</span>
        <span className="ml-1">{audience}</span>
      </div>
    </button>
  );
}



/* Optional: a ready-to-use grid with three modes */
function ModeGrid({ onSimple, onExtended, onDescribe }) {
  return (
    <div className="grid gap-4 sm:grid-cols-1">
      <ModeCard
        title="Simple"
        blurb="Answer 4–5 quick questions for fast, sensible picks."
        recommendedFor="quick decisions"
        Icon={Sparkles}
        onClick={onSimple}
      />
      <ModeCard
        title="Extended"
        blurb="Fine-tune more details (battery, size, storage, camera) for a closer match."
        recommendedFor="power shoppers"
        Icon={SlidersHorizontal}
        onClick={onExtended}
      />
      <ModeCard
        title="Describe"
        blurb="Type what you want in your own words and let the assistant figure it out."
        recommendedFor="free-form input"
        Icon={MessageSquareText}
        onClick={onDescribe}
      />
    </div>
  );
}


/* ---- InfoTip ---- */
function InfoTip({ text }) {
  if (!text) return null;
  return (
    <span className="relative group ml-2 mt-[2px] inline-flex select-none">
      <span className="inline-flex w-4 h-4 items-center justify-center rounded-full bg-slate-200 text-slate-700 text-[10px] font-semibold">
        i
      </span>
      <span
        className="
          pointer-events-none absolute z-50 left-1/2 -translate-x-1/2 top-[calc(100%+8px)]
          w-64 rounded-lg bg-black p-2 text-xs text-white shadow-lg
          opacity-0 translate-y-1 transition-all duration-150
          group-hover:opacity-100 group-hover:translate-y-0
        "
      >
        {text}
      </span>
    </span>
  );
}



/* ---- Wizard ---- */
function WizardStep({ stepIndex, total, stepDef, intent, onPatch, onBack, onNext }) {
  return (
    <div className="min-h-[68vh] flex items-center justify-center">
      <motion.div
        key={stepDef.key}
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}
        className="w-full max-w-2xl"
      >
        <div className="text-center text-base md:text-lg text-slate-500 mb-4">
          Step {stepIndex + 1} of {total}
        </div>

        <div className="bg-white rounded-3xl shadow p-8 md:p-10">
          <div className="text-center text-2xl md:text-3xl font-semibold">{stepDef.label}</div>

          <div className="mt-8">
            <StepControls type={stepDef.type} intent={intent} onPatch={onPatch} />
          </div>

          <div className="mt-10 flex items-center justify-between">
            <button
              className={`px-5 py-3 rounded-2xl border text-base md:text-lg ${stepIndex === 0 ? "opacity-40 cursor-not-allowed" : ""}`}
              onClick={onBack} disabled={stepIndex === 0}
            >
              ← Back
            </button>
            <button className="px-6 py-3 rounded-2xl bg-black text-white text-base md:text-lg" onClick={onNext}>
              {stepIndex + 1 === total ? "Finish" : "Next"}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}


function StepControls({ type, intent, onPatch }) {
  // keep numbers safe
  const asNumber = (x, def) => (Number.isFinite(x) ? x : def);

if (type === "budget") {
  const v = Number.isFinite(intent.budget) ? intent.budget : 700;
  return (
    <div className="text-center">
      <input
        type="range"
        min={200}
        max={2000}
        step={10}
        value={v}
        onChange={(e) => onPatch({ budget: Number(e.target.value) })}
        className="w-full h-3 accent-indigo-600"
      />
      <div className="mt-3 text-3xl font-semibold">${Math.round(v)}</div>
    </div>
  );
}

  if (type === "os") {
    const curr = intent.os || "No preference";
    const choose = (val) => onPatch({ os: val === "No preference" ? null : val });
    return <SegmentedBig options={["No preference", "Android", "iOS"]} value={curr} onChange={choose} />;
  }

  if (type === "size") {
    const toVal =
      intent?.prefer_small ? "Compact" :
      intent?.prefer_large ? "Larger"  :
      "No preference";
    const choose = (v) => {
      if (v === "No preference") onPatch({ prefer_small: null, prefer_large: null });
      else if (v === "Compact") onPatch({ prefer_small: true, prefer_large: null });
      else onPatch({ prefer_small: null, prefer_large: true });
    };
    return <SegmentedBig options={["No preference", "Compact", "Larger"]} value={toVal} onChange={choose} />;
  }

  if (type === "battery") {
    const v = intent.min_battery ? "Long battery" : "No preference";
    return (
      <SegmentedBig
        options={["No preference", "Long battery"]}
        value={v}
        onChange={(val) => onPatch({ min_battery: val === "Long battery" ? 5000 : null })}
      />
    );
  }

  if (type === "features") {
    const opts = ["5G", "Wireless charging", "IP68", "eSIM"];
    const selected = intent.must_have || [];
    const onChange = (arr) => onPatch({ must_have: arr.map((x) => x.toLowerCase()) });
    return <ChipsBig options={opts} selected={selected} onChange={onChange} />;
  }

  if (type === "brands") {
    const BR = ["Apple","Samsung","Google","OnePlus","Sony","Xiaomi","Motorola","Nothing","Oppo","Vivo","Realme"];
    return <ChipsBig options={BR} selected={intent.brands || []} onChange={(arr) => onPatch({ brands: arr })} />;
  }

  if (type === "ram") {
    const v = Number.isFinite(intent.min_ram) ? `${intent.min_ram} GB` : "No preference";
    const choose = (x) => onPatch({ min_ram: x === "No preference" ? null : Number(String(x).replace(/\D+/g,"")) });
    return <SegmentedBig options={["No preference", "6 GB", "8 GB", "12 GB"]} value={v} onChange={choose} />;
  }

  if (type === "storage") {
    const v = Number.isFinite(intent.min_storage) ? `${intent.min_storage} GB` : "No preference";
    const choose = (x) => onPatch({ min_storage: x === "No preference" ? null : Number(String(x).replace(/\D+/g,"")) });
    return <SegmentedBig options={["No preference", "128 GB", "256 GB", "512 GB"]} value={v} onChange={choose} />;
  }

  if (type === "camera") {
    const v = intent.camera_priority === true ? "Yes" :
              intent.camera_priority === false ? "No" : "No preference";
    const choose = (x) => onPatch({ camera_priority: x === "No preference" ? null : x === "Yes" });
    return <SegmentedBig options={["No preference", "Yes", "No"]} value={v} onChange={choose} />;
  }

  return null;
}

/* Bigger, centered segmented + chips */
function SegmentedBig({ options, value, onChange }) {
  const [local, setLocal] = React.useState(value);
  React.useEffect(() => setLocal(value), [value]);
  const choose = (opt) => { setLocal(opt); onChange?.(opt); };
  return (
    <div className="flex flex-wrap justify-center gap-4 md:gap-5">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => choose(opt)}
          className={`px-6 py-4 rounded-2xl border text-xl transition
            ${local === opt ? "bg-indigo-600 text-white border-indigo-600 shadow"
                            : "bg-white hover:bg-indigo-50 border-indigo-200"}`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
function ChipsBig({ options, selected = [], onChange }) {
  const [local, setLocal] = React.useState(new Set(selected));
  React.useEffect(() => setLocal(new Set(selected || [])), [selected]);
  const toggle = (opt) => {
    const next = new Set(local);
    if (next.has(opt)) next.delete(opt); else next.add(opt);
    setLocal(next); onChange?.(Array.from(next));
  };
  return (
    <div className="flex flex-wrap justify-center gap-4 md:gap-5">
      {options.map((opt) => (
        <button
          key={opt} type="button" onClick={() => toggle(opt)}
          className={`px-6 py-4 rounded-2xl border text-xl transition
            ${local.has(opt) ? "bg-indigo-600 text-white border-indigo-600 shadow"
                             : "bg-white hover:bg-indigo-50 border-indigo-200"}`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function BulletList({ items = [], pick, isCon = false }) {
  if (!items.length) return null;
  return (
    <div role="list" className="space-y-2">
      {items.map((text, i) => {
        const tip = findExplanation(pick, text, isCon);
        return (
          <div
            key={i}
            role="listitem"
            className="grid grid-cols-[1fr,16px] gap-2 items-start"
          >
            {/* left: custom dot + text (no browser list indent jitter) */}
            <div className="flex gap-2">
              <span className="mt-2 h-1.5 w-1.5 rounded-full bg-slate-400 flex-shrink-0" />
              <span className="text-sm text-slate-700">{text}</span>
            </div>
            {/* right: fixed 16px column so all (i)'s align */}
            <div className="mt-0.5">{tip ? <InfoTip text={tip} /> : null}</div>
          </div>
        );
      })}
    </div>
  );
}


/* ---- Results ---- */
function PhoneImage({ localSrc, remoteSrc, brandLogo, alt }) {
  const isLogo = !!brandLogo && !localSrc && !remoteSrc;
  const src = localSrc || remoteSrc || brandLogo || null;

  return (
    <div className={`w-full h-56 rounded-2xl flex items-center justify-center p-4
      ${isLogo ? "bg-white border-2 border-indigo-100" : "bg-slate-100"}`}>
      {src ? (
        <img
          src={src}
          alt={alt || ""}
          className="max-h-full max-w-full object-contain"
          loading="lazy"
        />
      ) : (
        <div className="text-slate-400">{alt || "No image"}</div>
      )}
    </div>
  );
}

/* ---------- Flippable phone card ---------- */
function FlippableCard({
  pick,
  variant = "featured",     // "featured" | "alt"
  showBlurb,
  blurb,
  onMakeMain,               // optional (shown on alt)
}) {
  const [flipped, setFlipped] = React.useState(false);
  const markets = React.useMemo(() => searchLinksForPick(pick), [pick]);

  // sizes / styles per variant
  const isFeatured = variant === "featured";
  const shell = isFeatured
    ? "max-w-5xl mx-auto rounded-3xl p-6 md:p-8"
    : "rounded-3xl p-4";

  return (
    <div className={`relative bg-white shadow ring-1 ring-slate-200 ${shell}`}>
      {/* badge + flip control row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {!isFeatured && (
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border">
              Alternative
            </span>
          )}
          <div className="text-lg md:text-xl font-semibold">
            {(pick?.Brand ?? "")} {(pick?.Model ?? "")}
          </div>
        </div>

        <button
          className="text-xs md:text-sm px-3 py-1.5 rounded-full border bg-slate-50 hover:bg-slate-100"
          onClick={() => setFlipped((f) => !f)}
          title={flipped ? "Back to details" : "Where to buy"}
        >
          {flipped ? "Back" : "Where to buy"}
        </button>
      </div>

      {/* card faces */}
      <div className="relative perspective-[1200px]">
        <div
          className={`transition-transform duration-500 [transform-style:preserve-3d] ${
            flipped ? "[transform:rotateY(180deg)]" : ""
          }`}
        >
          {/* FRONT */}
          <div className="grid md:grid-cols-[260px,1fr] gap-6 items-center [backface-visibility:hidden]">
            <div className="mx-auto w-full">
              <PhoneImage
                localSrc={pick?.ImageLocal}
                remoteSrc={pick?.ImageURL}
                brandLogo={pick?.BrandLogo}
                alt={`${pick?.Brand ?? ""} ${pick?.Model ?? ""}`}
              />
            </div>

            <div>
              {/* Specs row */}
              <div className="text-sm text-slate-500">
                {(pick?.OS ?? "—")} • {(pick?.ReleaseYear ?? "—")}
              </div>
              <div className="text-sm text-slate-500">
                {pick?.DisplayInches ? `${Number(pick.DisplayInches).toFixed(2)}"` : "—"} •{" "}
                {pick?.Battery_mAh ? `${pick.Battery_mAh} mAh` : "—"} •{" "}
                {pick?.RAM_GB ? `${pick.RAM_GB} GB RAM` : "—"} •{" "}
                {pick?.Storage_GB ? `${pick.Storage_GB} GB` : "—"}
              </div>

              {/* blurb only for featured (current main) */}
              {showBlurb && blurb ? (
                <div className="mt-3 bg-indigo-50 text-indigo-800 rounded-xl px-3 py-2 text-sm">
                  {blurb}
                </div>
              ) : null}

              {/* pros/cons */}
              {(pick?.Pros?.length || pick?.Cons?.length) ? (
                <div className="grid md:grid-cols-2 gap-6 mt-5">
                  <div>
                    <div className="text-sm font-medium">Why it fits</div>
                    <BulletList items={pick?.Pros || []} pick={pick} />
                  </div>
                  <div>
                    <div className="text-sm font-medium">Trade-offs</div>
                    <BulletList items={pick?.Cons || []} pick={pick} isCon />
                  </div>
                </div>
              ) : null}

              {/* Make main (only on alt) */}
              {!isFeatured && onMakeMain ? (
                <div className="mt-4">
                  <button
                    className="px-4 py-2 rounded-2xl bg-black text-white text-sm"
                    onClick={onMakeMain}
                    title="Promote to main pick"
                  >
                    Make main pick
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          {/* BACK (marketplaces) */}
          <div className="absolute inset-0 [backface-visibility:hidden] [transform:rotateY(180deg)]">
            <div className="h-full grid place-items-center">
              <div className="w-full">
                <div className="text-sm text-slate-600 mb-3">
                  Quick links (opens in new tab)
                </div>
                <div className="grid sm:grid-cols-3 gap-3">
                  {markets.map((m) => (
                    <a
                      key={m.id}
                      href={m.url}
                      target="_blank"
                      rel="noreferrer"
                      className="group flex items-center gap-3 border rounded-2xl px-3 py-2 hover:shadow-sm hover:bg-slate-50"
                      title={`Find ${pick?.Brand} ${pick?.Model} on ${m.name}`}
                    >
                      <div className="h-6 w-16 flex items-center justify-center overflow-hidden">
                        <img
                          src={m.logo}
                          alt={m.name}
                          className="object-contain max-h-6 max-w-[64px] opacity-80 group-hover:opacity-100"
                          loading="lazy"
                        />
                      </div>
                      <div className="text-sm">{m.name}</div>
                    </a>
                  ))}
                </div>
                <div className="mt-3 text-xs text-slate-500">
                  We’re not tracking prices here yet — these are search links for your region.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* DXOMARK badge (featured only if present) */}
      {variant === "featured" && "DxOMarkCameraRank" in (pick || {}) && (
        <div
          className="absolute right-4 bottom-4 rounded-2xl px-3 py-1 text-sm font-medium shadow-md"
          style={{ background: "rgba(0,0,0,0.75)", color: "white" }}
          title="DXOMARK Camera ranking"
        >
          DXOMARK • #{pick.DxOMarkCameraRank ?? "—"}
        </div>
      )}
    </div>
  );
}


function Bullet({ text, tip }) {
  return (
    <li className="grid grid-cols-[1fr,auto] gap-2 items-start">
      <span>{text}</span>
      {tip ? <InfoTip text={tip} /> : <span />}
    </li>
  );
}

function ResultsView({ picks, blurb }) {
  // Guard
  if (!Array.isArray(picks) || picks.length === 0) {
    return (
      <div className="bg-white rounded-2xl shadow p-8 text-slate-500">
        No suggestions yet — answer a couple of questions or press “Show results”.
      </div>
    );
  }

  // Local copy so we can animate reorder
  const [items, setItems] = React.useState(picks);
  const [featuredIdx, setFeaturedIdx] = React.useState(0);
  const [flipped, setFlipped] = React.useState(false); // front/back of FEATURED

  // Reset when new results arrive
  React.useEffect(() => {
    setItems(picks);
    setFeaturedIdx(0);
    setFlipped(false);
  }, [JSON.stringify(picks)]);

  const featured = items[featuredIdx];
  const rest = items.filter((_, i) => i !== featuredIdx);

  const makeMain = (idxInRest) => {
    // Find absolute index of the chosen item
    const absoluteIdx = items.findIndex((_, i) => i !== featuredIdx && (i > featuredIdx ? i - 1 : i) === idxInRest);
    if (absoluteIdx < 0) return;

    // Swap into position 0 with a nice layout animation
    setItems((prev) => {
      const next = [...prev];
      const [picked] = next.splice(absoluteIdx, 1);
      next.unshift(picked);
      return next;
    });
    setFeaturedIdx(0);
    setFlipped(false); // reset flip when changing featured
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Small subcomponent: quick marketplace strip (used ONLY on featured back face)
  const MarketStrip = ({ brand, model }) => {
    const links = buildMarketplaceLinks(brand, model); // expected to return [{id,label,logo,url}]
    return (
      <div className="mt-3 grid sm:grid-cols-3 gap-3">
        {links.map((m) => (
          <a
            key={m.id}
            href={m.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 hover:shadow"
          >
            {/* use stable public assets like /vendors/amazon.svg, /vendors/prisjakt.svg, /vendors/idealo.svg */}
            <img
              src={m.logo}
              alt={m.label}
              className="h-5 w-5 object-contain opacity-80"
              loading="lazy"
            />
            <span className="text-sm">{m.label}</span>
          </a>
        ))}
      </div>
    );
  };

  const heroBlurb = (featured?.Blurb || blurb || "").trim();

  return (
    <div className="space-y-8">
      {/* FEATURED CARD (flippable) */}
      <motion.div layout className="max-w-5xl mx-auto">
        <div className="relative" style={{ perspective: 1200 }}>
          <div
            className="relative transition-transform duration-500"
            style={{
              transform: flipped ? "rotateY(180deg)" : "none",
              transformStyle: "preserve-3d",
              willChange: "transform",
            }}
          >
            {/* FRONT FACE */}
            <div
              className="relative bg-white rounded-3xl shadow p-6 md:p-8 ring-1 ring-slate-200"
              style={{ backfaceVisibility: "hidden" }}
            >
              {/* DXOMARK badge — only on featured */}
              {"DxOMarkCameraRank" in (featured || {}) && (
                <div
                  className="absolute right-4 bottom-4 rounded-2xl px-3 py-1 text-sm font-medium shadow-md"
                  style={{ background: "rgba(0,0,0,0.75)", color: "white" }}
                  title="DXOMARK Camera ranking"
                >
                  DXOMARK • #{featured.DxOMarkCameraRank ?? "—"}
                </div>
              )}

              <div className="grid md:grid-cols-[260px,1fr] gap-6 items-center">
                <div className="mx-auto w-full">
                  <PhoneImage
                    localSrc={featured?.ImageLocal}
                    remoteSrc={featured?.ImageURL}
                    brandLogo={featured?.BrandLogo}
                    alt={`${featured?.Brand ?? ""} ${featured?.Model ?? ""}`}
                  />
                </div>

                <div>
                  {/* Title row */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-2xl md:text-3xl font-semibold">
                      {(featured?.Brand ?? "")} {(featured?.Model ?? "")}
                    </div>

                    {/* Only featured shows "Where to buy" (flips card) */}
                    <button
                      type="button"
                      onClick={() => setFlipped(true)}
                      className="shrink-0 rounded-xl px-3 py-1 text-sm border border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                      title="Show quick marketplace links"
                    >
                      Where to buy
                    </button>
                  </div>

                  {/* Subline with quick specs */}
                  <div className="text-sm text-slate-500 mt-1">
                    {(featured?.OS ?? "—")} • {(featured?.ReleaseYear ?? "—")}
                  </div>
                  <div className="text-sm text-slate-500">
                    {featured?.DisplayInches ? `${Number(featured.DisplayInches).toFixed(2)}"` : "—"} •{" "}
                    {featured?.Battery_mAh ? `${featured.Battery_mAh} mAh` : "—"} •{" "}
                    {featured?.RAM_GB ? `${featured.RAM_GB} GB RAM` : "—"} •{" "}
                    {featured?.Storage_GB ? `${featured.Storage_GB} GB` : "—"}
                  </div>

                  {/* Featured blurb — computed for all picks but ONLY visible on main */}
                  {heroBlurb && (
                    <div className="mt-3 bg-indigo-50 text-indigo-800 rounded-xl px-3 py-2 text-sm">
                      {heroBlurb}
                    </div>
                  )}

                  {(featured?.Pros?.length || featured?.Cons?.length) ? (
                    <div className="grid md:grid-cols-2 gap-6 mt-5">
                      <div>
                        <div className="text-sm font-medium">Why it fits</div>
                        <BulletList items={featured?.Pros || []} pick={featured} />
                      </div>
                      <div>
                        <div className="text-sm font-medium">Trade-offs</div>
                        <BulletList items={featured?.Cons || []} pick={featured} isCon />
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            {/* BACK FACE (quick links) */}
            <div
              className="absolute inset-0 rounded-3xl bg-white shadow p-6 md:p-8 ring-1 ring-slate-200"
              style={{ transform: "rotateY(180deg)", backfaceVisibility: "hidden" }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="text-lg md:text-xl font-semibold">
                  {(featured?.Brand ?? "")} {(featured?.Model ?? "")}
                </div>
                <button
                  type="button"
                  onClick={() => setFlipped(false)}
                  className="rounded-xl px-3 py-1 text-sm border border-slate-200 hover:bg-slate-50"
                  title="Back to details"
                >
                  Back
                </button>
              </div>

              <div className="mt-4 text-xs text-slate-500">Quick links (opens in new tab)</div>
              <MarketStrip brand={featured?.Brand} model={featured?.Model} />
              <div className="text-[11px] text-slate-400 mt-3">
                We’re not tracking prices yet — these are search links for your region.
              </div>
            </div>
          </div>
        </div>
      </motion.div>

      {/* ALTERNATIVES */}
      {rest.length > 0 && (
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-6">
          {rest.map((p, idx) => (
            <motion.div layout key={`${p?.Brand}-${p?.Model}-${idx}`} className="bg-white rounded-3xl shadow p-4 ring-1 ring-slate-200">
              {/* Label */}
              <div className="mb-2">
                <span className="inline-flex items-center rounded-full bg-slate-100 text-slate-700 text-xs px-2 py-0.5">
                  Alternative
                </span>
              </div>

              <PhoneImage
                localSrc={p?.ImageLocal}
                remoteSrc={p?.ImageURL}
                brandLogo={p?.BrandLogo}
                alt={`${p?.Brand ?? ""} ${p?.Model ?? ""}`}
              />

              <div className="mt-3">
                <div className="text-lg font-semibold">
                  {(p?.Brand ?? "")} {(p?.Model ?? "")}
                </div>

                {/* Subline */}
                <div className="text-xs text-slate-500">
                  {(p?.OS ?? "—")} • {(p?.ReleaseYear ?? "—")}
                </div>
                <div className="text-xs text-slate-500">
                  {p?.DisplayInches ? `${Number(p.DisplayInches).toFixed(2)}"` : "—"} •{" "}
                  {p?.Battery_mAh ? `${p.Battery_mAh} mAh` : "—"} •{" "}
                  {p?.RAM_GB ? `${p.RAM_GB} GB RAM` : "—"} •{" "}
                  {p?.Storage_GB ? `${p.Storage_GB} GB` : "—"}
                </div>

                {/* No links / blurb / DXOMARK on alternatives */}

                {(p?.Pros?.length || p?.Cons?.length) ? (
                  <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
                    <div>
                      <div className="text-sm font-medium">Pros</div>
                      <BulletList items={p?.Pros || []} pick={p} />
                    </div>
                    <div>
                      <div className="text-sm font-medium">Cons</div>
                      <BulletList items={p?.Cons || []} pick={p} isCon />
                    </div>
                  </div>
                ) : null}

                {/* Promote button */}
                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => makeMain(idx)}
                    className="rounded-2xl px-4 py-2 text-sm bg-black text-white hover:opacity-90"
                    title="Promote to main pick"
                  >
                    Make main
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}



/* ---- overlay ---- */
function SearchingOverlay() {
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/30 backdrop-blur-[1px] flex items-center justify-center z-50"
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-3xl shadow-xl p-8 w-[90%] max-w-md text-center"
      >
        <div className="mx-auto h-12 w-12 rounded-full border-4 border-slate-200 border-t-black animate-spin" />
        <div className="mt-4 text-xl font-semibold">Searching phones…</div>
        <div className="text-slate-600 mt-1">Matching your answers with our database.</div>
      </motion.div>
    </motion.div>
  );
}
