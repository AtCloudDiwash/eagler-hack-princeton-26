"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import type { AnalysisResult, PropertyDetail } from "@/lib/api-types";
import { buildingColor, colorFor, fmtDistance, titleCase } from "@/lib/format";
import { Card, EmptyNote, SectionTitle } from "@/components/ui/primitives";

const NeighborhoodMap = dynamic(() => import("@/components/map/NeighborhoodMap"), {
  ssr: false,
  loading: () => <div className="skeleton h-full w-full" />,
});

export default function NeighborhoodSection({ result, property }: { result: AnalysisResult; property: PropertyDetail }) {
  const nb = result.neighborhood;
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  if (!nb) {
    return (
      <section>
        <SectionTitle id="neighborhood" eyebrow="Location" title="Neighborhood" />
        <EmptyNote>No neighborhood data was collected for this analysis.</EmptyNote>
      </section>
    );
  }
  const groups = Object.entries(nb.place_groups).sort((a, b) => b[1] - a[1]);
  const mix = Object.entries(nb.building_mix).sort((a, b) => b[1] - a[1]);
  const mixTotal = mix.reduce((n, [, c]) => n + c, 0);
  const toggle = (g: string) =>
    setHidden((s) => {
      const n = new Set(s);
      if (n.has(g)) n.delete(g);
      else n.add(g);
      return n;
    });

  return (
    <section>
      <SectionTitle id="neighborhood" eyebrow="Location" title={`Neighborhood within ${fmtDistance(nb.radius_m)}`} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card className="h-[420px] overflow-hidden">
          <NeighborhoodMap
            neighborhood={nb}
            selected={{ lat: property.lat, lon: property.lon, footprint: property.footprint, label: property.address || "Selected building" }}
            hiddenGroups={hidden}
          />
        </Card>
        <div className="space-y-3">
          <Card className="p-4">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Why this radius</div>
            <p className="mt-1 text-[13px] leading-snug text-slate-300">{nb.radius_reason}</p>
          </Card>
          {nb.highlights.length > 0 && (
            <Card className="p-4">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Highlights</div>
              <ul className="space-y-1.5 text-[13px] leading-snug text-slate-200">
                {nb.highlights.map((h, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-violet-300">◆</span>
                    {h}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card className="p-4">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Places (click to toggle on map)</div>
            <div className="flex flex-wrap gap-1.5">
              {groups.map(([g, n]) => (
                <button
                  key={g}
                  onClick={() => toggle(g)}
                  className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] ${hidden.has(g) ? "border-line text-slate-600" : "border-line bg-ink-850 text-slate-200"}`}
                >
                  <i className="inline-block h-2 w-2 rounded-full" style={{ background: hidden.has(g) ? "#334155" : colorFor(g) }} />
                  {g} <span className="font-mono text-slate-500">{n}</span>
                </button>
              ))}
              {groups.length === 0 && <span className="text-xs text-slate-500">No place data.</span>}
            </div>
            {mixTotal > 0 && (
              <>
                <div className="mb-1 mt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Building mix</div>
                <div className="flex h-2.5 overflow-hidden rounded-full">
                  {mix.map(([t, n]) => (
                    <div key={t} title={`${titleCase(t)} ${n}`} style={{ width: `${(n / mixTotal) * 100}%`, background: buildingColor(t) }} />
                  ))}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-slate-400">
                  {mix.map(([t, n]) => (
                    <span key={t} className="flex items-center gap-1">
                      <i className="inline-block h-2 w-2 rounded-sm" style={{ background: buildingColor(t) }} />
                      {titleCase(t)} {n}
                    </span>
                  ))}
                </div>
              </>
            )}
          </Card>
        </div>
      </div>
    </section>
  );
}
