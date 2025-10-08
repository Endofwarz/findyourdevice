export default function ModePicker({ mode, onChange }) {
  return (
    <div className="flex items-center gap-2 bg-white/60 rounded-2xl p-2 shadow-inner">
      {["Guided", "Describe"].map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={`px-4 py-2 rounded-xl ${mode===m ? "bg-black text-white" : "hover:bg-black/5"}`}
        >
          {m}
        </button>
      ))}
    </div>
  );
}
