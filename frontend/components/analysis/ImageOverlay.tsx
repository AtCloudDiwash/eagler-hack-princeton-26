import { formatPercent, formatValue, humanize } from "@/lib/format";
import { boxToStyle, isFootprint, type BoxedEvidence } from "@/lib/overlay";
import { MediaImage } from "../MediaImage";
import { LiveDot } from "../ui/LiveDot";

/**
 * Image with absolutely positioned evidence boxes. Boxes are normalized, so percentages keep them
 * aligned at any rendered size. A building footprint is drawn dashed and beneath the other boxes,
 * with a visible "Building footprint" tag.
 */
export function OverlayImage({
  src,
  alt,
  evidence,
  placeholder,
}: {
  src: string | null;
  alt: string;
  evidence: BoxedEvidence[];
  placeholder: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-line bg-navy-900">
      <MediaImage src={src} alt={alt} fit="natural" placeholder={placeholder} />
      {src &&
        evidence.map((item, index) => {
          const footprint = isFootprint(item);
          return (
            <div
              key={`${item.key}-${index}`}
              data-testid="overlay-box"
              data-footprint={footprint || undefined}
              className={
                footprint
                  ? "absolute z-0 rounded-sm border-2 border-dashed border-accent/80"
                  : "group absolute z-10 rounded-sm border-2 border-accent bg-accent/15"
              }
              style={boxToStyle(item.box)}
              title={`${humanize(item.key)}: ${formatValue(item.value)}${item.note ? ` (${item.note})` : ""}`}
            >
              <span className="absolute -left-0.5 -top-0.5 flex items-center gap-1 rounded-br-sm bg-accent px-1 text-[10px] font-bold leading-4 text-navy-950">
                {index + 1}
                {footprint && <span className="font-semibold">Building footprint</span>}
              </span>
            </div>
          );
        })}
    </div>
  );
}

/** Numbered legend repeating each overlay finding as text (overlays only illustrate; the text is the record). */
export function EvidenceLegend({ evidence }: { evidence: BoxedEvidence[] }) {
  if (evidence.length === 0) {
    return <p className="text-xs text-ink-muted">No annotated findings for this image.</p>;
  }
  return (
    <ol className="grid gap-1 text-xs text-ink-muted">
      {evidence.map((item, index) => (
        <li key={`${item.key}-${index}`} className="flex gap-2">
          <span className="grid size-4 shrink-0 place-items-center rounded-sm bg-accent/20 text-[10px] font-bold text-accent">
            {index + 1}
          </span>
          <span>
            <span className="text-ink">{humanize(item.key)}:</span> {formatValue(item.value)}
            {item.note && <> · {item.note}</>}
            {item.confidence !== null && <> · {formatPercent(item.confidence)} confidence</>}
            {item.live && (
              <>
                {" "}
                <LiveDot live />
              </>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}

interface ImageOverlayProps {
  title: string;
  src: string | null;
  alt: string;
  evidence: BoxedEvidence[];
  placeholder: string;
}

/** Captioned overlay image + legend (used for the floor plan; the aerial has its own panel). */
export function ImageOverlay({ title, src, alt, evidence, placeholder }: ImageOverlayProps) {
  return (
    <figure className="grid content-start gap-2">
      <figcaption className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{title}</figcaption>
      <OverlayImage src={src} alt={alt} evidence={evidence} placeholder={placeholder} />
      <EvidenceLegend evidence={evidence} />
    </figure>
  );
}
