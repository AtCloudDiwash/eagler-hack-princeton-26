"use client";

import { MapPinned } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import type { AnalysisResult, PropertyDetail } from "@/lib/api-types";
import { buildingColor, fmtDistance } from "@/lib/format";
import { heightFor } from "@/lib/geo";
import { groupIdForLabel, placeMeta } from "@/lib/places";
import type { MapBuilding } from "@/components/map/TurnkeyMap";
import { LayerToggle } from "@/components/shell/Shell";
import { EmptyNote } from "@/components/ui/primitives";

const TurnkeyMap = dynamic(() => import("@/components/map/TurnkeyMap"), { ssr: false, loading: () => <div className="skeleton absolute inset-0" /> });

export default function LocationTab({ result, property }: { result: AnalysisResult; property: PropertyDetail }) {
  const nb = result.neighborhood;
  const [layer, setLayer] = useState<"aerial" | "map">("aerial");
  const [tilt, setTilt] = useState(false);
  const [visible, setVisible] = useState<Set<string> | null>(null);
  const groups = Object.entries(nb?.place_groups ?? {}).sort((a, b) => b[1] - a[1]);
  const buildings = useMemo<MapBuilding[]>(() => {
    const list: MapBuilding[] = [{ id: property.id, lat: property.lat, lon: property.lon, footprint: property.footprint, height: heightFor(property.stories_est), kind: "subject" }];
    for (const b of nb?.buildings ?? []) list.push({ id: `nb-${b.id}`, lat: b.lat, lon: b.lon, footprint: b.footprint, height: 7, kind: "neighbor", color: buildingColor(b.building_type) });
    return list;
  }, [nb, property]);
  if (!nb) return <EmptyNote>No neighborhood data for this analysis.</EmptyNote>;
  const toggle = (gid: string) => {
    const all = groups.map(([l]) => groupIdForLabel(l));
    const cur = new Set(visible ?? all);
    if (cur.has(gid)) cur.delete(gid);
    else cur.add(gid);
    setVisible(cur.size === all.length ? null : cur);
  };
  const zoom = Math.max(13.6, 16.4 - Math.log2(nb.radius_m / 200));
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="relative h-[420px] overflow-hidden rounded-2xl ring-1 ring-white/[0.06]">
        <TurnkeyMap
          layer={layer}
          tilt={tilt}
          buildings={buildings}
          places={nb.places}
          visibleGroups={visible}
          ring={{ center: [property.lon, property.lat], radius: nb.radius_m, color: "#a78bfa" }}
          ringKey="loc"
          parcel={property.parcel}
          initial={{ lon: property.lon, lat: property.lat, zoom, pitch: 50, bearing: -18 }}
        />
        <LayerToggle layer={layer} onChange={setLayer} tilt={tilt} onTilt={setTilt} className="absolute right-3 top-3" />
      </div>
      <div className="space-y-4">
        <div className="rounded-xl bg-white/[0.03] p-3 ring-1 ring-inset ring-white/[0.05]">
          <div className="mb-1 flex items-center gap-2 text-[12px] font-medium text-slate-200">
            <MapPinned size={13} className="text-violet-300" /> Why {fmtDistance(nb.radius_m)}?
          </div>
          <p className="text-[12px] leading-relaxed text-slate-400">{nb.radius_reason}</p>
        </div>
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Nearby · tap to toggle</div>
          <div className="flex flex-wrap gap-1.5">
            {groups.map(([label, n]) => {
              const gid = groupIdForLabel(label);
              const on = !visible || visible.has(gid);
              return (
                <button key={label} onClick={() => toggle(gid)} className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] ring-1 ring-inset transition ${on ? "bg-white/[0.05] text-slate-200 ring-white/[0.08]" : "text-slate-600 ring-white/[0.04] line-through"}`}>
                  <i className="h-2 w-2 rounded-full" style={{ background: placeMeta(gid).color, opacity: on ? 1 : 0.3 }} />
                  {label}
                  <span className="font-mono text-slate-500">{n}</span>
                </button>
              );
            })}
          </div>
        </div>
        {Object.keys(nb.stats ?? {}).length > 0 && (
          <dl className="grid grid-cols-2 gap-2">
            {Object.entries(nb.stats)
              .filter(([, v]) => v !== null && v !== "")
              .slice(0, 6)
              .map(([k, v]) => (
                <div key={k} className="rounded-lg bg-white/[0.03] p-2 ring-1 ring-inset ring-white/[0.05]">
                  <dt className="text-[10px] uppercase tracking-wide text-slate-500">{k.replace(/_/g, " ")}</dt>
                  <dd className="mt-0.5 text-sm font-semibold text-slate-100">{typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : v}</dd>
                </div>
              ))}
          </dl>
        )}
      </div>
    </div>
  );
}
