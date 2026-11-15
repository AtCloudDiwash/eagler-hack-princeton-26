"use client";

import { CheckCircle2, CircleAlert, CircleHelp, ClipboardList, DoorOpen, Droplets, Flame, Layers3, Ruler, Timer, Users } from "lucide-react";
import type { ReactNode } from "react";
import type { CheckStatus, SiteCheck, SpaceProgram } from "@/lib/api-types";
import { AGENT_META, fmtNum } from "@/lib/format";
import { Collapsible, EmptyNote } from "@/components/ui/primitives";

const CHECK_UI: Record<CheckStatus, { icon: ReactNode; cls: string; label: string }> = {
  pass: { icon: <CheckCircle2 size={13} />, cls: "text-emerald-300", label: "Meets" },
  risk: { icon: <CircleAlert size={13} />, cls: "text-amber-300", label: "Conflict" },
  unknown: { icon: <CircleHelp size={13} />, cls: "text-slate-400", label: "Verify" },
};
const GROUND = { required: "Ground floor required", preferred: "Ground floor preferred", any: "Any floor" } as const;
const TIMELINE_CLS = { ok: "text-emerald-300", tight: "text-amber-300", risk: "text-rose-300" } as const;

function Fact({ icon, label, value, hint }: { icon: ReactNode; label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-white/[0.03] px-2.5 py-2 ring-1 ring-inset ring-white/[0.05]" title={hint}>
      <span className="mt-0.5 text-teal-300">{icon}</span>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
        <div className="text-[12px] font-medium leading-snug text-slate-100">{value}</div>
      </div>
    </div>
  );
}

function NeedChips({ program }: { program: SpaceProgram }) {
  if (!program.needs.length) return null;
  const sorted = [...program.needs].sort((a, b) => Number(a.priority !== "must") - Number(b.priority !== "must"));
  return (
    <div className="flex flex-wrap gap-1.5">
      {sorted.map((n) => (
        <span
          key={n.id}
          title={`${n.triggers}\nChecked by the ${AGENT_META[n.owner].label}`}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset ${n.priority === "must" ? "bg-teal-300/15 text-teal-100 ring-teal-300/40" : "bg-white/[0.04] text-slate-300 ring-white/[0.08]"}`}
        >
          {n.priority === "must" ? "Must" : "Nice"} · {n.label}
        </span>
      ))}
    </div>
  );
}

function codeValue(p: SpaceProgram, id: string) {
  return p.code.find((c) => c.id === id);
}

/** "What you need": the request turned into size, occupancy and code requirements. */
export function ProgramSummary({ program, compact = false }: { program: SpaceProgram; compact?: boolean }) {
  const occ = program.occupancy;
  const exits = codeValue(program, "exits");
  const rest = codeValue(program, "restrooms");
  const spr = codeValue(program, "sprinklers");
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-1.5">
        <Fact icon={<Ruler size={12} />} label="Space" value={`${fmtNum(program.size.min_sqft)}–${fmtNum(program.size.max_sqft)} sq ft`} hint={program.size.basis.join("\n")} />
        <Fact icon={<Users size={12} />} label="Occupancy" value={`~${occ.occupant_load} people · Group ${occ.group}`} hint={occ.basis.join("\n")} />
        {exits && <Fact icon={<DoorOpen size={12} />} label="Exits" value={exits.value} hint={exits.detail} />}
        {rest && <Fact icon={<Droplets size={12} />} label="Restrooms" value={rest.value.split(",")[0]} hint={rest.detail} />}
        {!compact && spr && <Fact icon={<Flame size={12} />} label="Sprinklers" value={spr.value} hint={spr.detail} />}
        {!compact && <Fact icon={<Layers3 size={12} />} label="Building" value={`${GROUND[program.building.ground_floor]} · ${program.building.min_ceiling_ft}+ ft ceilings`} hint={program.building.ceiling_reason} />}
      </div>
      <NeedChips program={program} />
      {program.timeline && (
        <p className={`flex items-start gap-1.5 text-[11px] leading-snug ${TIMELINE_CLS[program.timeline.status]}`}>
          <Timer size={12} className="mt-0.5 shrink-0" /> {program.timeline.detail}
        </p>
      )}
      {(program.near.length > 0 || program.avoid.length > 0 || program.tenure === "buy") && (
        <p className="text-[11px] text-slate-400">
          {program.tenure === "buy" && <span className="mr-2 text-slate-200">Buying, not leasing.</span>}
          {program.near.length > 0 && <span className="mr-2">Near: {program.near.join(", ")}.</span>}
          {program.avoid.length > 0 && <span>Avoid: {program.avoid.join(", ")}.</span>}
        </p>
      )}
      <Collapsible title={<span className="text-[11px]">How we worked this out</span>}>
        <ul className="space-y-1 text-[11px] leading-snug text-slate-400">
          {program.size.basis.map((b) => (
            <li key={b}>• {b}</li>
          ))}
          {occ.basis.map((b) => (
            <li key={b}>• {b}</li>
          ))}
          {program.code.map((c) => (
            <li key={c.id}>
              • <span className="text-slate-200">{c.rule}:</span> {c.detail} {c.citation && <span className="text-slate-500">({c.citation})</span>}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[10px] text-slate-500">{program.disclaimer}</p>
      </Collapsible>
    </div>
  );
}

/** Compact "we understood" panel shown under the search results. */
export function ProgramPanel({ program }: { program: SpaceProgram }) {
  return (
    <div className="mt-3 rounded-xl bg-white/[0.02] p-2.5 ring-1 ring-inset ring-white/[0.05]">
      <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-300/80">
        <ClipboardList size={11} /> What you need
      </div>
      <ProgramSummary program={program} compact />
    </div>
  );
}

/** Dashboard tab: the program next to how this building measures up against it. */
export function NeedsTab({ program, checks }: { program: SpaceProgram | undefined; checks: SiteCheck[] | undefined }) {
  if (!program) return <EmptyNote>This analysis was run before requirements were tracked. Run it again to see them.</EmptyNote>;
  const order: Record<CheckStatus, number> = { risk: 0, unknown: 1, pass: 2 };
  const sorted = [...(checks ?? [])].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-400/80">What you asked for</div>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {program.acknowledged.map((a) => (
            <span key={a.label} title={a.source === "stated" ? "From your request" : a.source === "derived" ? "Worked out from your request" : "Typical default (not stated)"} className={`rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset ${a.source === "stated" ? "bg-teal-300/10 text-teal-100 ring-teal-300/30" : a.source === "derived" ? "bg-white/[0.04] text-slate-200 ring-white/[0.08]" : "text-slate-500 ring-white/[0.06]"}`}>
              {a.label}
            </span>
          ))}
        </div>
        <ProgramSummary program={program} />
      </div>
      <div>
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-400/80">How this building measures up</div>
        {sorted.length ? (
          <ul className="space-y-1.5">
            {sorted.map((c) => (
              <li key={c.id} className="flex items-start gap-2 rounded-xl bg-white/[0.03] p-2.5 ring-1 ring-inset ring-white/[0.05]">
                <span className={`mt-0.5 ${CHECK_UI[c.status].cls}`}>{CHECK_UI[c.status].icon}</span>
                <div className="min-w-0">
                  <div className="text-[12px] font-medium text-slate-100">
                    {c.label} <span className={`ml-1 text-[10px] font-normal ${CHECK_UI[c.status].cls}`}>{CHECK_UI[c.status].label}</span>
                  </div>
                  <p className="text-[11px] leading-snug text-slate-400">{c.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyNote>No building data to compare against.</EmptyNote>
        )}
        {program.needs.length > 0 && (
          <div className="mt-4">
            <div className="mb-1.5 text-[10px] uppercase tracking-wide text-slate-500">Who checked your needs</div>
            <ul className="space-y-1 text-[11px] text-slate-400">
              {program.needs.map((n) => (
                <li key={n.id} className="flex items-center gap-2">
                  <i className="h-1.5 w-1.5 rounded-full" style={{ background: AGENT_META[n.owner].color }} />
                  <span className="text-slate-200">{n.label}</span>
                  <span className="text-slate-500">({n.priority === "must" ? "must-have" : "nice-to-have"}) · {AGENT_META[n.owner].label}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
