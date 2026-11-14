"use client";

import type { Neighborhood } from "@/lib/api-types";
import { buildingColor, colorFor, fmtDistance, titleCase } from "@/lib/format";
import { Spinner } from "@/components/ui/primitives";

type Props = {
  radius: number;
  setRadius: (r: number) => void;
  neighborhood: Neighborhood | null;
  loading: boolean;
  error: string | null;
};

const SOURCE_CLS = { used: "text-teal-300", unavailable: "text-slate-500 line-through", demo: "text-amber-300" } as const;

export default function NeighborhoodControls({ radius, setRadius, neighborhood, loading, error }: Props) {
  const mix = Object.entries(neighborhood?.building_mix ?? {}).sort((a, b) => b[1] - a[1]);
  const mixTotal = mix.reduce((n, [, c]) => n + c, 0);
  const groups = Object.entries(neighborhood?.place_groups ?? {}).sort((a, b) => b[1] - a[1]);
  const stats = Object.entries(neighborhood?.stats ?? {}).filter(([, v]) => v !== null && v !== "");

  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="font-medium text-slate-300">Neighborhood radius</span>
          <span className="flex items-center gap-1.5 font-mono text-teal-300">
            {loading && <Spinner className="h-3 w-3" />}
            {fmtDistance(radius)}
          </span>
        </div>
        <input
          type="range"
          min={100}
          max={1500}
          step={50}
          value={radius}
          onChange={(e) => setRadius(Number(e.target.value))}
          className="w-full accent-teal-500"
          aria-label="Neighborhood radius in meters"
        />
        <div className="flex justify-between text-[10px] text-slate-600">
          <span>100 m</span>
          <span>1.5 km</span>
        </div>
      </div>

      {error && <p className="text-xs text-rose-300">{error}</p>}

      {neighborhood && (
        <>
          {mixTotal > 0 && (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Building mix · {mixTotal} buildings</div>
              <div className="flex h-2.5 w-full overflow-hidden rounded-full">
                {mix.map(([t, n]) => (
                  <div key={t} title={`${titleCase(t)}: ${n}`} style={{ width: `${(n / mixTotal) * 100}%`, background: buildingColor(t) }} />
                ))}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
                {mix.map(([t, n]) => (
                  <span key={t} className="flex items-center gap-1">
                    <i className="inline-block h-2 w-2 rounded-sm" style={{ background: buildingColor(t) }} />
                    {titleCase(t)} {n}
                  </span>
                ))}
              </div>
            </div>
          )}

          {groups.length > 0 && (
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Nearby places</div>
              <div className="grid grid-cols-2 gap-1">
                {groups.map(([g, n]) => (
                  <div key={g} className="flex items-center justify-between rounded-lg bg-ink-850 px-2 py-1 text-[11px]">
                    <span className="flex min-w-0 items-center gap-1.5 text-slate-300">
                      <i className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: colorFor(g) }} />
                      <span className="truncate">{g}</span>
                    </span>
                    <span className="font-mono text-slate-400">{n}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {stats.length > 0 && (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
              {stats.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <dt className="text-slate-500">{titleCase(k)}</dt>
                  <dd className="text-slate-200">{typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : v}</dd>
                </div>
              ))}
            </dl>
          )}

          {neighborhood.sources.length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px]">
              {neighborhood.sources.map((s) => (
                <span key={s.name} title={s.note} className={SOURCE_CLS[s.status]}>
                  ● {s.name}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
