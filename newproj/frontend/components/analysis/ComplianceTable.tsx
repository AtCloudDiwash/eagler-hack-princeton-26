"use client";

import { useState } from "react";
import type { ComplianceItem } from "@/lib/api-types";
import { COMPLIANCE_STYLE } from "@/lib/format";
import { Card, EmptyNote, Pill, SectionTitle } from "@/components/ui/primitives";
import { EvidenceChips } from "./EvidenceContext";

export default function ComplianceTable({ items }: { items: ComplianceItem[] }) {
  const counts = items.reduce<Record<string, number>>((m, i) => ({ ...m, [i.status]: (m[i.status] ?? 0) + 1 }), {});
  return (
    <section>
      <SectionTitle
        id="compliance"
        eyebrow="Regulatory"
        title="Compliance findings"
        right={
          <div className="flex gap-1.5">
            {(["pass", "risk", "fail", "unknown"] as const).map((s) =>
              counts[s] ? (
                <Pill key={s} className={COMPLIANCE_STYLE[s].cls}>
                  {counts[s]} {COMPLIANCE_STYLE[s].label}
                </Pill>
              ) : null,
            )}
          </div>
        }
      />
      {items.length === 0 ? (
        <EmptyNote>The compliance agent did not return rule checks.</EmptyNote>
      ) : (
        <Card className="divide-y divide-line/70">
          {items.map((c) => (
            <Row key={c.id} c={c} />
          ))}
        </Card>
      )}
      <p className="mt-2 text-[11px] text-slate-500">Decision support only — confirm with the city and a licensed professional before signing a lease.</p>
    </section>
  );
}

function Row({ c }: { c: ComplianceItem }) {
  const [open, setOpen] = useState(false);
  const st = COMPLIANCE_STYLE[c.status] ?? COMPLIANCE_STYLE.unknown;
  return (
    <div className="p-4">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-3 text-left">
        <Pill className={`${st.cls} mt-0.5 w-16 justify-center`}>{st.label}</Pill>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-slate-100">{c.rule}</div>
          <p className={`mt-0.5 text-[12px] leading-snug text-slate-400 ${open ? "" : "line-clamp-2"}`}>{c.detail}</p>
        </div>
        <span className={`text-slate-500 transition-transform ${open ? "rotate-90" : ""}`}>›</span>
      </button>
      {open && (
        <div className="ml-[76px] mt-2 space-y-1.5 text-[11px]">
          {c.citation && (
            <div className="text-slate-400">
              <span className="text-slate-500">Citation: </span>
              {c.url ? (
                <a href={c.url} target="_blank" rel="noreferrer" className="text-teal-300 hover:underline">
                  {c.citation} ↗
                </a>
              ) : (
                c.citation
              )}
            </div>
          )}
          {c.evidence_ids.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-slate-500">Evidence</span>
              <EvidenceChips ids={c.evidence_ids} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
