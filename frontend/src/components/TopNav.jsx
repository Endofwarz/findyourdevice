// frontend/src/components/TopNav.jsx
import React from "react";
import { Smartphone, Tablet, Laptop, Watch, Headphones, Tv, Gamepad2 } from "lucide-react";

const cats = [
  { key: "phones", label: "Phones", Icon: Smartphone, active: true },
  { key: "tablets", label: "Tablets", Icon: Tablet, disabled: true },
  { key: "laptops", label: "Laptops", Icon: Laptop, disabled: true },
  { key: "watches", label: "Watches", Icon: Watch, disabled: true },
  { key: "earbuds", label: "Earbuds", Icon: Headphones, disabled: true },
  { key: "tvs", label: "TVs", Icon: Tv, disabled: true },
  { key: "consoles", label: "Consoles", Icon: Gamepad2, disabled: true },
];

export default function TopNav({ onHome }) {
  return (
    <header className="sticky top-0 z-30 h-16 bg-white/80 backdrop-blur border-b border-slate-200">
      <div className="mx-auto max-w-6xl h-full px-4 flex items-center justify-between">
        {/* Left: tiny logo/name */}
        <button
          onClick={onHome}
          className="flex items-center gap-2 text-slate-800 hover:opacity-90"
          title="Home"
        >
          <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 shadow" />
          <span className="font-semibold">Find your tech</span>
        </button>

        {/* Center: category strip */}
        <nav className="hidden md:flex items-center gap-2">
          {cats.map(({ key, label, Icon, active, disabled }) => (
            <button
              key={key}
              className={[
                "px-3 py-1.5 rounded-2xl border text-sm inline-flex items-center gap-2 transition",
                active
                  ? "bg-indigo-600 text-white border-indigo-600 shadow"
                  : disabled
                  ? "bg-white text-slate-400 border-slate-200 cursor-not-allowed opacity-60"
                  : "bg-white hover:bg-indigo-50 text-slate-700 border-slate-200",
              ].join(" ")}
              disabled={disabled}
              title={disabled ? "Coming soon" : label}
            >
              <Icon className={active ? "h-4 w-4 text-white" : "h-4 w-4 text-indigo-600"} />
              {label}
            </button>
          ))}
        </nav>

        {/* Right: actions (placeholder) */}
        <div className="flex items-center gap-2">
          <button
            className="text-sm px-3 py-1.5 rounded-xl border border-slate-200 hover:bg-slate-50"
            onClick={onHome}
          >
            Start over
          </button>
        </div>
      </div>
    </header>
  );
}
