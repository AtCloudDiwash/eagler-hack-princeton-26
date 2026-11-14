import { formatPercent, formatValue, humanize } from "@/lib/format";
import { boxToStyle, type BoxedEvidence } from "@/lib/overlay";
import { MediaImage } from "../MediaImage";

interface ImageOverlayProps {
  title: string;
  src: string | null;
  alt: string;
  evidence: BoxedEvidence[];
  placeholder: string;
}

/**
 * Image with absolutely positioned evidence boxes. Boxes are normalized, so percentages keep them
 * aligned at any rendered size. A numbered legend repeats each finding as text (overlays only
 * illustrate; the text is the record).
 */
export function ImageOverlay({ title, src, alt, evidence, placeholder }: ImageOverlayProps) {
  return (
    <figure className="grid gap-2">
      <figcaption className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{title}</figcaption>
      <div className="relative overflow-hidden rounded-lg border border-line bg-navy-900">
        <MediaImage src={src} alt={alt} fit="natural" placeholder={placeholder} />
        {src &&
          evidence.map((item, index) => (
            <div
              key={`${item.key}-${index}`}
              data-testid="overlay-box"
              className="group absolute rounded-sm border-2 border-accent bg-accent/15"
              style={boxToStyle(item.box)}
              title={`${humanize(item.key)}: ${formatValue(item.value)}${item.note ? ` (${item.note})` : ""}`}
            >
              <span className="absolute -left-0.5 -top-0.5 grid size-4 place-items-center rounded-br-sm bg-accent text-[10px] font-bold text-navy-950">
                {index + 1}
              </span>
            </div>
          ))}
      </div>
      {evidence.length > 0 ? (
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
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-xs text-ink-muted">No annotated findings for this image.</p>
      )}
    </figure>
  );
}
