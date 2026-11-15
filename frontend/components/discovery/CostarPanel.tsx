"use client";

import { Building, KeyRound } from "lucide-react";
import type { CostarSpace, CostarSummary, SpaceProgram } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { leasingRows } from "@/lib/costar-spaces";

const rent = (s: CostarSpace) => (s.rent_per_sqft_yr ? `$${s.rent_per_sqft_yr.toFixed(2)}/sq ft/yr` : "Call for rate");
const SERVICE: Record<string, string> = { TripleNet: "NNN", FullService: "Full service", ModifiedGross: "Mod. gross", Net: "Net", DoubleNet: "NN", IndustrialGross: "Ind. gross" };

/** CoStar's leasing figures for the selected building: rentable area and the spaces on the market. */
export default function CostarPanel({ costar, program, selectedSpace }: { costar: CostarSummary; program: SpaceProgram | null; selectedSpace?: CostarSpace | null }) {
  const lo = program?.size.min_sqft ?? 0;
  const hi = program?.size.max_sqft ?? Infinity;
  const spaces = leasingRows(costar.spaces, selectedSpace, program?.size);
  return (
    <div className="rounded-xl bg-white/[0.025] p-3 ring-1 ring-inset ring-white/[0.05]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs font-semibold text-slate-200">
          <KeyRound size={13} className="text-emerald-300" /> Leasing · CoStar
        </h4>
        <span className="text-[10px] text-slate-500" title={`Matched ${costar.match}`}>{costar.type ?? ""}</span>
      </div>
      <dl className="mb-2 grid grid-cols-3 gap-1.5 text-[11px]">
        <div className="rounded-lg bg-white/[0.03] p-2" title="Rentable Building Area: inside the walls, excluding stairs and elevator shafts; CoStar's leasing basis (GLA for retail)">
          <dt className="text-[10px] uppercase tracking-wide text-slate-500">Rentable ({costar.rentable_basis ?? "RBA"})</dt>
          <dd className="font-semibold text-slate-100">{costar.rentable_sqft ? `${fmtNum(costar.rentable_sqft)} sq ft` : "—"}</dd>
        </div>
        <div className="rounded-lg bg-white/[0.03] p-2" title="Sum of spaces marketed for lease (not lease-pending)">
          <dt className="text-[10px] uppercase tracking-wide text-slate-500">Available</dt>
          <dd className="font-semibold text-emerald-200">{costar.available_sqft ? `${fmtNum(costar.available_sqft)} sq ft` : "None listed"}</dd>
        </div>
        <div className="rounded-lg bg-white/[0.03] p-2" title="Asking rent range across listed spaces, normalised to $/sq ft/year">
          <dt className="text-[10px] uppercase tracking-wide text-slate-500">Asking</dt>
          <dd className="font-semibold text-slate-100">{costar.asking_rent_per_sqft_yr ? `$${costar.asking_rent_per_sqft_yr[0].toFixed(0)}–${costar.asking_rent_per_sqft_yr[1].toFixed(0)}/sf/yr` : "—"}</dd>
        </div>
      </dl>
      {spaces.length > 0 ? (
        <ul aria-label="Listed suites" className="max-h-48 space-y-1 overflow-y-auto pr-1">
          {spaces.map(({ space: s, selected, fits }, i) => (
            <li key={`${s.listing_id}-${s.suite}-${s.floor}-${i}`} data-selected-space={selected || undefined} className={`flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-[11px] ring-1 ring-inset ${selected ? "bg-teal-400/[0.12] ring-teal-300/60" : fits ? "bg-emerald-400/[0.08] ring-emerald-300/30" : "bg-white/[0.02] ring-white/[0.04]"}`}>
              <span className="flex min-w-0 items-center gap-1.5 text-slate-200">
                <Building size={11} className="shrink-0 text-slate-500" />
                <span className="min-w-0">
                  {selected && <span className="block text-[9px] font-semibold uppercase tracking-wide text-teal-300">Suggested space</span>}
                  <span className="block truncate">{s.suite ? `Suite ${s.suite}` : "Space"}
                  {s.floor ? ` · ${s.floor}` : ""}
                  {s.lease_pending ? " · pending" : ""}</span>
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="font-semibold text-slate-100">{!selected && s.sqft_min && s.sqft_max && s.sqft_min < s.sqft_max ? `${fmtNum(s.sqft_min)}–${fmtNum(s.sqft_max)} sq ft` : s.sqft ? `${fmtNum(s.sqft)} sq ft` : "—"}</span>
                <span className="ml-1.5 text-slate-400">{rent(s)}</span>
                {s.service && <span className="ml-1 text-slate-500">{SERVICE[s.service] ?? s.service}</span>}
                {selected && s.suggested_portion && <span className="mt-0.5 block text-[10px] text-amber-200">Proposed portion · listed {fmtNum(s.sqft_min)}–{fmtNum(s.sqft_max)} sq ft<br />Confirm division with landlord</span>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[11px] text-slate-500">No spaces on the market in the CoStar data for this building.</p>
      )}
      {program && spaces.length > 0 && (
        <p className="mt-1.5 text-[10px] text-slate-500">{selectedSpace && "The suggested space is used for size and cost estimates. Other suites are alternatives. "}Highlighted suites fit your {fmtNum(lo)}–{fmtNum(hi)} sq ft range.</p>
      )}
      <p className="mt-1.5 text-[10px] leading-snug text-slate-600">{costar.note}</p>
    </div>
  );
}
