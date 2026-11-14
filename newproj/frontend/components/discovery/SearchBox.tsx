"use client";

import { type FormEvent } from "react";
import { Spinner } from "@/components/ui/primitives";

export const EXAMPLES = [
  "I want to open a 40-seat restaurant in Houston",
  "Dental clinic in Houston",
  "Find a location for a gym in Los Angeles",
  "Gym in Princeton",
];

type Props = {
  query: string;
  setQuery: (q: string) => void;
  onSearch: (q: string) => void;
  loading: boolean;
  showExamples: boolean;
};

export default function SearchBox({ query, setQuery, onSearch, loading, showExamples }: Props) {
  function submit(e: FormEvent) {
    e.preventDefault();
    if (query.trim()) onSearch(query.trim());
  }
  return (
    <div>
      <form onSubmit={submit} className="flex items-start gap-2 rounded-xl border border-line bg-ink-950/70 p-2 focus-within:border-teal-500/60">
        <svg viewBox="0 0 24 24" className="ml-1 mt-2 h-4 w-4 shrink-0 text-teal-400" fill="none" stroke="currentColor" strokeWidth={2}>
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (query.trim()) onSearch(query.trim());
            }
          }}
          rows={2}
          placeholder="Describe what you want to open and where — e.g. “a 40-seat restaurant in Houston”"
          className="min-h-[2.75rem] flex-1 resize-none bg-transparent py-1 text-sm leading-snug text-slate-100 placeholder:text-slate-500 focus:outline-none"
          aria-label="Describe your business and location"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="flex h-9 items-center gap-1.5 self-end rounded-lg bg-teal-500 px-3 text-sm font-semibold text-ink-950 hover:bg-teal-400 disabled:opacity-40"
        >
          {loading ? <Spinner className="h-4 w-4 text-ink-950" /> : "Find"}
        </button>
      </form>
      {showExamples && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setQuery(ex);
                onSearch(ex);
              }}
              className="rounded-full border border-line bg-ink-850 px-2.5 py-1 text-[11px] text-slate-300 hover:border-teal-400 hover:text-teal-300"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
