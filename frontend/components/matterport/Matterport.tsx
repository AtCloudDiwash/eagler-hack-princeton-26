"use client";

import { Box, CheckCircle2, CircleAlert, Link2, Unlink } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import type { AgentReport, MatterportLink, PropertyDetail } from "@/lib/api-types";
import { fmtSqft } from "@/lib/format";
import { EvidenceChips } from "@/components/analysis/EvidenceContext";
import { EmptyNote, Pill, Spinner } from "@/components/ui/primitives";

const DATA_BADGE: Record<MatterportLink["data"], { label: string; cls: string }> = {
  live: { label: "Live · Model API", cls: "bg-teal-400/10 text-teal-200 ring-teal-300/30" },
  recorded: { label: "Recorded scan", cls: "bg-sky-400/10 text-sky-200 ring-sky-300/30" },
  embed_only: { label: "Tour only", cls: "bg-amber-400/10 text-amber-200 ring-amber-300/30" },
};

/** The public Matterport showcase in an iframe (no key needed; the backend never exposes credentials). */
export function MatterportEmbed({ link, className = "h-56" }: { link: MatterportLink; className?: string }) {
  return (
    <div className={`relative overflow-hidden rounded-xl bg-black/40 ring-1 ring-inset ring-white/[0.08] ${className}`}>
      <iframe
        src={link.embed_url}
        title={`Matterport 3D tour ${link.model_id}`}
        className="absolute inset-0 h-full w-full"
        allow="xr-spatial-tracking; fullscreen"
        allowFullScreen
        loading="lazy"
      />
    </div>
  );
}

/** Building panel: paste a tour link, preview it, unlink it. */
export function MatterportLinker({ property, onChange }: { property: PropertyDetail; onChange: (d: PropertyDetail) => void }) {
  const [tour, setTour] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const link = property.matterport ?? null;

  const run = async (fn: () => Promise<PropertyDetail>) => {
    setBusy(true);
    setError(null);
    try {
      onChange(await fn());
      setTour("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl bg-white/[0.025] p-3 ring-1 ring-inset ring-white/[0.05]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs font-semibold text-slate-200">
          <Box size={13} className="text-sky-300" /> Interior · Matterport 3D tour
        </h4>
        {link && <Pill className={DATA_BADGE[link.data].cls}>{DATA_BADGE[link.data].label}</Pill>}
      </div>

      {link ? (
        <div className="space-y-2">
          <MatterportEmbed link={link} />
          {link.scan && (
            <p className="flex items-center gap-1.5 text-[11px] text-slate-300">
              <CheckCircle2 size={12} className="text-teal-300" />
              {link.scan.name ?? link.model_id}: {link.scan.floors} floor(s), {link.scan.rooms} rooms
              {link.scan.total_indoor_area_sqft ? `, ${fmtSqft(link.scan.total_indoor_area_sqft)} measured` : ""}
            </p>
          )}
          <p className="text-[11px] leading-snug text-slate-500">{link.note}</p>
          <button onClick={() => run(() => api.unlinkMatterport(property.id))} disabled={busy} className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-rose-300 disabled:opacity-50">
            <Unlink size={12} /> Unlink tour
          </button>
        </div>
      ) : (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (tour.trim()) run(() => api.linkMatterport(property.id, tour.trim()));
          }}
        >
          <p className="text-[11px] leading-snug text-slate-500">Have a 3D tour of this space? Paste it and the Matterport Agent will check the interior: rooms, restrooms, kitchen, ceiling heights.</p>
          <div className="flex gap-1.5">
            <input
              value={tour}
              onChange={(e) => setTour(e.target.value)}
              placeholder="https://my.matterport.com/show/?m=…"
              className="min-w-0 flex-1 rounded-lg bg-white/[0.04] px-2.5 py-2 text-[12px] text-slate-100 ring-1 ring-inset ring-white/[0.06] placeholder:text-slate-500 focus:outline-none focus:ring-sky-300/40"
            />
            <button type="submit" disabled={busy || !tour.trim()} className="flex items-center gap-1 rounded-lg bg-sky-300/90 px-3 text-[12px] font-semibold text-ink-950 hover:bg-sky-200 disabled:opacity-40">
              {busy ? <Spinner className="h-3.5 w-3.5 text-ink-950" /> : <Link2 size={13} />} Link
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-rose-300">
          <CircleAlert size={12} className="mt-0.5 shrink-0" /> {error}
        </p>
      )}
    </div>
  );
}

/** Dashboard tab: the 3D tour next to what the Matterport Agent concluded from it. */
export function InteriorTab({ link, report }: { link: MatterportLink; report: AgentReport | undefined }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <div className="space-y-2">
        <MatterportEmbed link={link} className="h-[26rem]" />
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <Pill className={DATA_BADGE[link.data].cls}>{DATA_BADGE[link.data].label}</Pill>
          <span>{link.note}</span>
        </div>
      </div>
      <div className="space-y-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-sky-300/80">Matterport Agent</div>
        {report ? (
          <>
            <p className="text-[13px] leading-relaxed text-slate-200">{report.summary}</p>
            <ul className="space-y-2">
              {report.findings.map((f) => (
                <li key={f.id} className="rounded-xl bg-white/[0.03] p-2.5 ring-1 ring-inset ring-white/[0.05]">
                  <div className="flex items-start justify-between gap-2">
                    <span className={`text-[12px] font-medium ${f.impact === "positive" ? "text-emerald-200" : f.impact === "negative" ? "text-rose-200" : "text-slate-200"}`}>{f.title}</span>
                    <EvidenceChips ids={f.evidence_ids} />
                  </div>
                  <p className="mt-1 text-[11px] leading-snug text-slate-400">{f.detail}</p>
                </li>
              ))}
            </ul>
            {report.missing_information.length > 0 && (
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Still to verify on site</div>
                <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-slate-400">
                  {report.missing_information.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <EmptyNote>The Matterport Agent did not report for this analysis.</EmptyNote>
        )}
      </div>
    </div>
  );
}
