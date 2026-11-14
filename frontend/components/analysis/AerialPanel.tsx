"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { overlayEvidence } from "@/lib/overlay";
import type { AnalysisResult } from "@/lib/types";
import { MediaImage } from "../MediaImage";
import { Badge } from "../ui/Badge";
import { EvidenceLegend, OverlayImage } from "./ImageOverlay";

type View = "top" | "angled";

const VIEWS: Array<{ id: View; label: string }> = [
  { id: "top", label: "Top-down" },
  { id: "angled", label: "Angled" },
];

/** Shown under live imagery when the backend omits the attribution (Vexcel requires one). */
const DEFAULT_VEXCEL_ATTRIBUTION = "Imagery © Vexcel Imaging";

/**
 * Vexcel aerial: top-down ortho with evidence overlays, plus an "Angled" (oblique) tab when the backend
 * has one. Live imagery gets a "Live · Vexcel" badge and the required attribution line; anything else
 * (mock mode, older runs without `aerial_source`) is labelled as placeholder imagery.
 */
export function AerialPanel({ result }: { result: AnalysisResult }) {
  const media = result.media;
  const aerialUrl = media?.aerial_url ?? null;
  const obliqueUrl = media?.oblique_url ?? null;
  const live = media?.aerial_source === "vexcel-live";
  const attribution = live ? media?.aerial_attribution?.trim() || DEFAULT_VEXCEL_ATTRIBUTION : null;
  const evidence = overlayEvidence(result, "vexcel");

  const [view, setView] = useState<View>("top");
  const baseId = useId();
  const tabId = (v: View) => `${baseId}-tab-${v}`;
  const panelId = (v: View) => `${baseId}-panel-${v}`;
  const activeView: View = obliqueUrl ? view : "top";

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next: View = activeView === "top" ? "angled" : "top";
    setView(next);
    document.getElementById(tabId(next))?.focus();
  }

  const topDown = (
    <OverlayImage src={aerialUrl} alt={`Aerial view of ${result.address}`} evidence={evidence} placeholder="No aerial image" />
  );

  return (
    <figure className="grid content-start gap-2">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
          Aerial · Vexcel
          {live ? (
            <span data-testid="aerial-live">
              <Badge tone="accent" title="Live imagery from the Vexcel API">
                <span className="size-1.5 rounded-full bg-accent" aria-hidden />
                Live · Vexcel
              </Badge>
            </span>
          ) : (
            aerialUrl && (
              <span data-testid="aerial-placeholder" className="font-normal normal-case tracking-normal text-ink-muted/80">
                Placeholder imagery
              </span>
            )
          )}
        </span>
        {obliqueUrl && (
          <div role="tablist" aria-label="Aerial view" className="flex rounded-md border border-line bg-navy-900 p-0.5 text-xs">
            {VIEWS.map(({ id, label }) => {
              const selected = activeView === id;
              return (
                <button
                  key={id}
                  id={tabId(id)}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={panelId(id)}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => setView(id)}
                  onKeyDown={onTabKeyDown}
                  className={`rounded px-2 py-1 font-medium transition-colors ${
                    selected ? "bg-accent/15 text-accent" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}
      </figcaption>

      {obliqueUrl ? (
        <>
          <div role="tabpanel" id={panelId("top")} aria-labelledby={tabId("top")} hidden={activeView !== "top"}>
            {topDown}
          </div>
          <div role="tabpanel" id={panelId("angled")} aria-labelledby={tabId("angled")} hidden={activeView !== "angled"}>
            {/* Fixed 4:3 frame so switching tabs doesn't shift the layout; the whole photo stays visible. */}
            <div className="relative aspect-[4/3] overflow-hidden rounded-lg border border-line bg-navy-900">
              <MediaImage src={obliqueUrl} alt={`Angled aerial view of ${result.address}`} fit="contain" placeholder="No angled image" />
            </div>
            <p className="mt-1 text-xs text-ink-muted">Overlays are drawn on the top-down view.</p>
          </div>
        </>
      ) : (
        topDown
      )}

      {attribution && (
        <p data-testid="aerial-attribution" className="text-[11px] text-ink-muted">
          {attribution}
        </p>
      )}
      <EvidenceLegend evidence={evidence} />
    </figure>
  );
}
