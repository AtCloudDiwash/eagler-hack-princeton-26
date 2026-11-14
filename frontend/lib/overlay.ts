// Helpers for drawing evidence boxes over aerial (Vexcel) and floor-plan (Matterport) images.
// Contract rule: evidence with source "vexcel" + box goes on media.aerial_url, "matterport" + box on
// media.floor_plan_url. Boxes are normalized [x, y, w, h] so they scale with the rendered image.

import type { AnalysisResult, Evidence, OverlayBox } from "./types";

export interface OverlayStyle {
  left: string;
  top: string;
  width: string;
  height: string;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));
const pct = (value: number) => `${Number((value * 100).toFixed(2))}%`;

/** Normalized box -> absolute-position percentages, clamped so it never spills outside the image. */
export function boxToStyle(box: OverlayBox): OverlayStyle {
  const [rawX, rawY, rawW, rawH] = box;
  const x = clamp01(rawX);
  const y = clamp01(rawY);
  const w = Math.min(clamp01(rawW), 1 - x);
  const h = Math.min(clamp01(rawH), 1 - y);
  return { left: pct(x), top: pct(y), width: pct(w), height: pct(h) };
}

export type OverlaySource = "vexcel" | "matterport";

export type BoxedEvidence = Evidence & { box: OverlayBox };

function hasBox(evidence: Evidence): evidence is BoxedEvidence {
  return Array.isArray(evidence.box) && evidence.box.length === 4 && evidence.box.every((n) => typeof n === "number");
}

/**
 * All evidence for one image source that carries a box: observations first, then evidence attached
 * to criteria results, de-duplicated by key + box so the same fact is not drawn twice.
 */
export function overlayEvidence(result: AnalysisResult, source: OverlaySource): BoxedEvidence[] {
  const candidates = [
    ...Object.values(result.observations ?? {}),
    ...(result.criteria_results ?? []).flatMap((criterion) => criterion.evidence ?? []),
  ];
  const seen = new Set<string>();
  const boxed: BoxedEvidence[] = [];
  for (const evidence of candidates) {
    if (!evidence || evidence.source !== source || !hasBox(evidence)) continue;
    const id = `${evidence.key}:${evidence.box.join(",")}`;
    if (seen.has(id)) continue;
    seen.add(id);
    boxed.push(evidence);
  }
  return boxed;
}
