import type { CostarSpace } from "./api-types";

type SizeRange = { min_sqft: number; max_sqft: number };

/** Keep the suite used by the summary and costs first; other rows are alternatives. */
export function leasingRows(spaces: CostarSpace[], selected: CostarSpace | null | undefined, range?: SizeRange) {
  const sameSelection = (space: CostarSpace) => !!selected &&
    space.listing_id === selected.listing_id && space.suite === selected.suite && space.floor === selected.floor;
  const listed = spaces.map((space) => sameSelection(space) ? { ...space, ...selected } : space);
  // Older summaries may have clipped the chosen suite from their list.
  if (selected && !listed.some(sameSelection)) listed.push(selected);
  return listed.map((space) => ({
    space,
    selected: sameSelection(space),
    fits: !!range && !!space.sqft && !space.lease_pending &&
      (space.sqft_min || space.sqft) <= range.max_sqft && (space.sqft_max || space.sqft) >= range.min_sqft,
  })).sort((a, b) => Number(b.selected) - Number(a.selected) || Number(b.fits) - Number(a.fits));
}
