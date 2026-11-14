import { CubeTransparentIcon } from "@heroicons/react/24/outline";
import { overlayEvidence } from "@/lib/overlay";
import type { AnalysisResult } from "@/lib/types";
import { ImageOverlay } from "./ImageOverlay";

/** Aerial (Vexcel) + floor plan (Matterport) with evidence overlays, and the 3D tour when available. */
export function MediaPanel({ result }: { result: AnalysisResult }) {
  const { media } = result;
  return (
    <div className="grid gap-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <ImageOverlay
          title="Aerial · Vexcel"
          src={media?.aerial_url ?? null}
          alt={`Aerial view of ${result.address}`}
          evidence={overlayEvidence(result, "vexcel")}
          placeholder="No aerial image"
        />
        <ImageOverlay
          title="Floor plan · Matterport"
          src={media?.floor_plan_url ?? null}
          alt={`Floor plan of ${result.address}`}
          evidence={overlayEvidence(result, "matterport")}
          placeholder="No floor plan"
        />
      </div>
      <div className="grid gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">3D tour</p>
        {media?.matterport_embed_url ? (
          <iframe
            src={media.matterport_embed_url}
            title={`3D tour of ${result.address}`}
            className="aspect-video w-full rounded-lg border border-line bg-navy-900"
            allow="fullscreen; xr-spatial-tracking"
            allowFullScreen
            loading="lazy"
          />
        ) : (
          <div className="flex items-center gap-3 rounded-lg border border-dashed border-line bg-navy-900/60 p-4 text-sm text-ink-muted">
            <CubeTransparentIcon className="size-6 shrink-0" aria-hidden />
            No Matterport 3D tour for this listing (mock mode or not published by the landlord).
          </div>
        )}
      </div>
    </div>
  );
}
