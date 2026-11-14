"use client";

export type BaseLayer = "aerial" | "street";

export function LayerToggle({ layer, onChange, className = "" }: { layer: BaseLayer; onChange: (l: BaseLayer) => void; className?: string }) {
  return (
    <div className={`flex overflow-hidden rounded-xl border border-line bg-ink-900/95 text-xs shadow-xl backdrop-blur ${className}`}>
      {(["aerial", "street"] as const).map((l) => (
        <button
          key={l}
          onClick={() => onChange(l)}
          className={`px-3 py-1.5 font-medium ${layer === l ? "bg-teal-500 text-ink-950" : "text-slate-300 hover:bg-ink-800"}`}
        >
          {l === "aerial" ? "Vexcel aerial" : "Map"}
        </button>
      ))}
    </div>
  );
}
