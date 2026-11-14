"use client";

import { MagnifyingGlassIcon } from "@heroicons/react/20/solid";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, toQuery } from "@/lib/api";
import type { BusinessType } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { Button } from "./ui/Button";

/** Used when GET /api/v1/business-types fails so the form still works offline. */
export const FALLBACK_BUSINESS_TYPES: BusinessType[] = [
  { id: "restaurant", label: "Restaurant", capacity_unit: "seats", default_capacity: 40, needs_kitchen: true },
  { id: "dental_clinic", label: "Dental clinic", capacity_unit: "chairs", default_capacity: 4, needs_kitchen: false },
];

/** Example requirement sentence derived from the business type config (no per-type hard-coding). */
export function exampleDetails(type: BusinessType | undefined): string {
  if (!type) return "e.g. 40 seats, kitchen needed, 2 bathrooms, 20 parking spaces";
  const kitchen = type.needs_kitchen ? ", kitchen needed" : "";
  return `${type.default_capacity} ${type.capacity_unit}${kitchen}, 2 bathrooms, 20 parking spaces`;
}

const inputClass =
  "w-full rounded-lg border border-line bg-navy-900 px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted/60 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

export function BusinessProfileForm() {
  const router = useRouter();
  const typesState = useAsync((signal) => api.businessTypes({ signal }), "business-types");
  const types =
    typesState.status === "success" && typesState.data.length > 0 ? typesState.data : FALLBACK_BUSINESS_TYPES;

  const [typeId, setTypeId] = useState("restaurant");
  const [details, setDetails] = useState("");
  const [city, setCity] = useState("Houston");
  const [state, setState] = useState("TX");

  // If the configured list doesn't contain the current choice, fall back to the first entry.
  const selectedType = types.find((t) => t.id === typeId) ?? types[0];
  const example = exampleDetails(selectedType);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedType) return;
    router.push(`/properties${toQuery({ type: selectedType.id, details, city, state })}`);
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4 rounded-xl border border-line bg-surface p-5 shadow-lg shadow-black/20 sm:p-6">
      <div className="grid gap-1.5">
        <label htmlFor="business-type" className="text-sm font-medium">
          Business type
        </label>
        <select
          id="business-type"
          value={selectedType?.id ?? ""}
          onChange={(e) => setTypeId(e.target.value)}
          className={inputClass}
        >
          {types.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
        {typesState.status === "error" && (
          <p className="text-xs text-ink-muted">API unavailable — showing default business types.</p>
        )}
      </div>

      <div className="grid gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="details" className="text-sm font-medium">
            What do you need?
          </label>
          <button type="button" onClick={() => setDetails(example)} className="text-xs text-accent hover:underline">
            Use example
          </button>
        </div>
        <input
          id="details"
          value={details}
          onChange={(e) => setDetails(e.target.value)}
          placeholder={`e.g. ${example}`}
          className={inputClass}
        />
        <p className="text-xs text-ink-muted">
          Plain English is fine. Anything you leave out is filled from local guidelines and listed as an assumption.
        </p>
      </div>

      <div className="grid grid-cols-[1fr_6rem] gap-3">
        <div className="grid gap-1.5">
          <label htmlFor="city" className="text-sm font-medium">
            City or ZIP
          </label>
          <input id="city" value={city} onChange={(e) => setCity(e.target.value)} required className={inputClass} />
        </div>
        <div className="grid gap-1.5">
          <label htmlFor="state" className="text-sm font-medium">
            State
          </label>
          <input
            id="state"
            value={state}
            onChange={(e) => setState(e.target.value.toUpperCase())}
            minLength={2}
            maxLength={2}
            required
            className={`${inputClass} uppercase`}
          />
        </div>
      </div>

      <Button type="submit" className="mt-1 w-full sm:w-auto sm:justify-self-end">
        <MagnifyingGlassIcon className="size-4" aria-hidden />
        Find spaces
      </Button>
    </form>
  );
}
