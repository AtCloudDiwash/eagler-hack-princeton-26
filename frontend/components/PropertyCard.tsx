"use client";

import { CheckIcon } from "@heroicons/react/20/solid";
import { formatCurrency, formatRent, formatSqft, orNA } from "@/lib/format";
import type { Property } from "@/lib/types";
import { MediaImage } from "./MediaImage";
import { Badge } from "./ui/Badge";

interface PropertyCardProps {
  property: Property;
  selected: boolean;
  onToggle: (id: string) => void;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="truncate text-sm font-medium" title={value}>
        {value}
      </dd>
    </div>
  );
}

/** One listing on the selection page. The whole card toggles selection (via its checkbox label). */
export function PropertyCard({ property, selected, onToggle }: PropertyCardProps) {
  const ti =
    property.ti_allowance_per_sqft === null
      ? "N/A"
      : `${formatCurrency(property.ti_allowance_per_sqft)}/sq ft`;
  const inputId = `select-${property.id}`;

  return (
    <label
      htmlFor={inputId}
      className={`group flex cursor-pointer flex-col overflow-hidden rounded-xl border bg-surface shadow-lg shadow-black/20 transition-colors ${
        selected ? "border-accent ring-1 ring-accent" : "border-line hover:border-accent/50"
      }`}
    >
      <div className="relative aspect-[16/10] bg-navy-900">
        <MediaImage src={property.image_url} alt={`Listing photo of ${property.address}`} />
        <div className="absolute left-3 top-3 flex gap-1.5">
          {!property.available && <Badge tone="risk">Unavailable</Badge>}
        </div>
        <span
          aria-hidden
          className={`absolute right-3 top-3 grid size-7 place-items-center rounded-md border-2 transition-colors ${
            selected ? "border-accent bg-accent text-navy-950" : "border-ink/70 bg-navy-950/70 text-transparent"
          }`}
        >
          <CheckIcon className="size-5" />
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start gap-3">
          <input
            id={inputId}
            type="checkbox"
            checked={selected}
            onChange={() => onToggle(property.id)}
            className="sr-only"
          />
          <div className="min-w-0">
            <h3 className="font-semibold leading-snug">{property.address}</h3>
            <p className="text-sm text-ink-muted">
              {property.city}, {property.state} {property.zip}
            </p>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          <Stat label="Size" value={formatSqft(property.size_sqft)} />
          <Stat label="Rent" value={formatRent(property.rent)} />
          <Stat label="Zoning" value={orNA(property.zoning)} />
          <Stat label="TI allowance" value={ti} />
          <div className="col-span-2">
            <Stat label="Previous use" value={orNA(property.previous_use)} />
          </div>
        </dl>
        <p className={`mt-auto text-sm font-medium ${selected ? "text-accent" : "text-ink-muted group-hover:text-ink"}`}>
          {selected ? "Selected for comparison" : "Select to compare"}
        </p>
      </div>
    </label>
  );
}
