"use client";

import { ArrowLeft, Crosshair, Layers, Radius, X } from "lucide-react";
import { fmtDistance } from "@/lib/format";

/** Radius choices for "Within"; null = everything the place data covers (1.5 km). */
export const RADIUS_STEPS: (number | null)[] = [null, 1000, 500, 250];

type Props = {
  around: string; // the anchor's label, the selected building or "Map view"
  aroundIsPlace: boolean; // a clicked/found place can be cleared back to the building or map
  onClearAround: () => void;
  radius: number | null;
  onRadius: (r: number | null) => void;
  showing: string[]; // labels of the place groups on the map
  onClearShowing: () => void;
  canBack: boolean;
  onBack: () => void;
};

const chip = "flex h-[22px] items-center gap-1 rounded-md bg-white/[0.06] px-1.5 text-[10.5px] text-slate-200 ring-1 ring-inset ring-white/[0.08]";

/** What follow-up questions refer to: "Around: Near Cafe · Within: 500 m · Showing: Parking". Each chip is editable. */
export default function MapContextStrip(p: Props) {
  const nextRadius = () => p.onRadius(RADIUS_STEPS[(RADIUS_STEPS.indexOf(p.radius) + 1) % RADIUS_STEPS.length]);
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1">
      {p.canBack && (
        <button onClick={p.onBack} className={`${chip} text-teal-200 hover:bg-white/[0.1]`} title="Restore the previous map results">
          <ArrowLeft size={11} /> Back
        </button>
      )}
      <span className={chip} title="Questions like “what's around it?” refer to this">
        <Crosshair size={11} className="text-teal-300" />
        <span className="text-slate-400">Around</span>
        <span className="max-w-[130px] truncate text-slate-100">{p.around}</span>
        {p.aroundIsPlace && (
          <button onClick={p.onClearAround} className="text-slate-500 hover:text-white" aria-label="Stop focusing this place">
            <X size={11} />
          </button>
        )}
      </span>
      <button onClick={nextRadius} className={`${chip} hover:bg-white/[0.1]`} title="Change how far to look (click to cycle)">
        <Radius size={11} className="text-teal-300" />
        <span className="text-slate-400">Within</span>
        <span className="text-slate-100">{p.radius == null ? "1.5 km" : fmtDistance(p.radius)}</span>
      </button>
      {p.showing.length > 0 && (
        <span className={chip}>
          <Layers size={11} className="text-teal-300" />
          <span className="text-slate-400">Showing</span>
          <span className="max-w-[130px] truncate text-slate-100">{p.showing.length > 2 ? `${p.showing.slice(0, 2).join(", ")} +${p.showing.length - 2}` : p.showing.join(", ")}</span>
          <button onClick={p.onClearShowing} className="text-slate-500 hover:text-white" aria-label="Clear places from the map">
            <X size={11} />
          </button>
        </span>
      )}
    </div>
  );
}
