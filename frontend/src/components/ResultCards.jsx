// frontend/src/components/ResultCards.jsx
function clamp(n, lo, hi){ return Math.min(Math.max(n, lo), hi); }

function estimatePrice(p){
  const year = +p.ReleaseYear || 2022;
  const brand = (p.Brand||"").toString().trim();
  const ram = +p.RAM_GB || 4;
  const storage = +p.Storage_GB || 64;
  const battery = +p.Battery_mAh || 4000;
  const cam = +p.MainCameraMP || 12;

  let base = 350;
  if (year >= 2025) base = 600;
  else if (year === 2024) base = 550;
  else if (year === 2023) base = 500;

  // spec lifts
  base += Math.max(0, ram - 6) * 18;
  base += Math.max(0, storage - 128) * 1.2;
  base += Math.max(0, battery - 4500) * 0.05;
  base += Math.max(0, cam - 48) * 2.0;

  const BF = {
    Apple:1.35, Samsung:1.2, Google:1.15, OnePlus:1.05, Sony:1.15, Xiaomi:0.95,
    Motorola:0.9, Nothing:1.0, Asus:1.05, Oppo:0.95, Vivo:0.95, Realme:0.9,
    Honor:0.95, Huawei:1.0, Nokia:0.85, Lenovo:0.85, Tecno:0.8, Infinix:0.8,
    ZTE:0.85, Meizu:0.9, LG:0.9, HTC:0.95, Micromax:0.75, BLU:0.75,
  };
  const factor = BF[brand] ?? 1.0;
  let price = base * factor;
  price = clamp(price, 120, 1600);
  return Math.round(price / 10) * 10; // nearest $10
}

function displayPrice(p){
  const v = +p.PriceUSD;
  if (!v || Number.isNaN(v) || v < 160) return estimatePrice(p);
  // if the given price looks too low vs our estimate for recent big brands, prefer estimate
  const bigBrand = /apple|samsung|google|oneplus|sony/i.test(p.Brand||"");
  const recent = (+p.ReleaseYear || 0) >= 2023;
  const est = estimatePrice(p);
  if (bigBrand && recent && est > v * 1.3) return est;
  return Math.round(v);
}

function svgDataURL(label){
  const safe = (label || "Phone").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const gradA = "#111827", gradB = "#1f2937";
  const svg = `
<svg xmlns='http://www.w3.org/2000/svg' width='640' height='400'>
  <defs>
    <linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>
      <stop offset='0%' stop-color='${gradA}' />
      <stop offset='100%' stop-color='${gradB}' />
    </linearGradient>
  </defs>
  <rect width='100%' height='100%' fill='url(#g)'/>
  <text x='50%' y='50%' text-anchor='middle' dominant-baseline='middle'
        font-family='Inter, Segoe UI, Arial, sans-serif' font-size='28' fill='white'>${safe}</text>
</svg>`;
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

function ensureImageURL(p){
  if (p.ImageURL && String(p.ImageURL).startsWith("data:")) return p.ImageURL;
  const label = `${p.Brand||""} ${p.Model||""}`.trim() || "Phone";
  return p.ImageURL || svgDataURL(label);
}

function prosConsFromSpec(p){
  const pros=[], cons=[];
  const w=+p.Weight_g||0, batt=+p.Battery_mAh||0, disp=+p.DisplayInches||0;
  const ram=+p.RAM_GB||0, store=+p.Storage_GB||0, cam=+p.MainCameraMP||0;
  if (batt >= 4800) pros.push("Long battery life");
  if (ram >= 8) pros.push("Plenty of RAM");
  if (store >= 256) pros.push("Large storage");
  if (disp <= 6.2) pros.push("Compact size");
  if (disp >= 6.7) pros.push("Large, immersive display");
  if (cam >= 50) pros.push("High-res main camera");
  if (w > 205) cons.push("On the heavy side");
  if (store <= 128) cons.push("Limited storage");
  if (ram <= 6) cons.push("Entry RAM");
  return {pros, cons};
}

function Price({ value }){
  if (value==null || Number.isNaN(+value)) return <span className="text-slate-400">n/a</span>;
  return <span>${Number(value).toFixed(0)}</span>;
}

function Photo({ p }){
  const url = ensureImageURL(p);
  return (
    <div className="w-full aspect-[16/10] overflow-hidden rounded-xl bg-slate-100">
      <img src={url} alt="" className="w-full h-full object-cover" />
    </div>
  );
}

export function PrimaryCard({ p, blurb }){
  const pc = prosConsFromSpec(p);
  const price = displayPrice(p);
  return (
    <div className="col-span-2 rounded-3xl p-6 bg-white shadow-soft border space-y-4">
      <Photo p={p}/>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xl font-semibold">{p.Brand} {p.Model}</h3>
          <div className="text-slate-500 text-sm">{p.OS} • {p.ReleaseYear || "?"}</div>
        </div>
        <div className="text-2xl font-bold"><Price value={price}/></div>
      </div>
      {blurb && <p className="text-sm leading-6">{blurb}</p>}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="font-medium mb-1">Pros</div>
          <ul className="text-sm list-disc ml-5 space-y-1">
            {pc.pros.slice(0,4).map((x,i)=> <li key={i}>{x}</li>)}
          </ul>
        </div>
        <div>
          <div className="font-medium mb-1">Cons</div>
          <ul className="text-sm list-disc ml-5 space-y-1">
            {pc.cons.slice(0,4).map((x,i)=> <li key={i}>{x}</li>)}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function AltCard({ p, blurb }){
  const price = displayPrice(p);
  return (
    <div className="rounded-2xl p-5 bg-white shadow-soft border space-y-3">
      <Photo p={p}/>
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold">{p.Brand} {p.Model}</div>
          <div className="text-slate-500 text-sm">{p.OS} • {p.ReleaseYear || "?"}</div>
        </div>
        <div className="font-bold"><Price value={price}/></div>
      </div>
      {blurb && <p className="text-sm leading-5">{blurb}</p>}
      <div className="text-xs text-slate-500">
        • {(+p.DisplayInches || "?")}″ • {(+p.Battery_mAh || "?")} mAh • {(+p.RAM_GB || "?")} GB RAM • {(+p.Storage_GB || "?")} GB
      </div>
    </div>
  );
}
