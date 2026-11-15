"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Briefcase, Clock, Dumbbell, Search, ShoppingBag, Sparkles, Stethoscope, Utensils, X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Spinner } from "@/components/ui/primitives";

const EXAMPLES: { q: string; icon: ReactNode }[] = [
  { q: "I want to open a 40-seat restaurant in Houston", icon: <Utensils size={14} /> },
  { q: "Dental clinic in Houston with parking, budget $9k/month", icon: <Stethoscope size={14} /> },
  { q: "Gym around 5,000 sq ft in Los Angeles", icon: <Dumbbell size={14} /> },
  { q: "Retail store in Houston with good foot traffic", icon: <ShoppingBag size={14} /> },
  { q: "Office for a 12-person startup in Houston", icon: <Briefcase size={14} /> },
];

/** Follow-ups offered once there are results: keep talking until the matches look right. */
const REFINE_EXAMPLES: { q: string; icon: ReactNode }[] = [
  { q: "Only spaces on the ground floor", icon: <Sparkles size={14} /> },
  { q: "My budget is $8k a month", icon: <Sparkles size={14} /> },
  { q: "Make it bigger, around 2,500 sq ft", icon: <Sparkles size={14} /> },
  { q: "It must have parking", icon: <Sparkles size={14} /> },
  { q: "Which of these have a space listed for lease?", icon: <Sparkles size={14} /> },
];

const RECENT_KEY = "turnkey:recent";
export function loadRecents(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").slice(0, 5);
  } catch {
    return [];
  }
}
export function pushRecent(q: string) {
  try {
    const list = [q, ...loadRecents().filter((x) => x !== q)].slice(0, 5);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable */
  }
}

type Props = {
  query: string;
  setQuery: (q: string) => void;
  onSearch: (q: string) => void;
  loading: boolean;
  /** Open the suggestions on first load so new users see what to type. */
  idle: boolean;
  /** "refine": there are results; the bar talks to the agent to change them (no recents, follow-up examples). */
  mode?: "search" | "refine";
};

/** Search bar docked at the bottom center; suggestions rise above it. */
export default function SearchDock({ query, setQuery, onSearch, loading, idle, mode = "search" }: Props) {
  const refining = mode === "refine";
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(-1);
  const [recents, setRecents] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => setRecents(loadRecents()), [loading]);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (refining) return REFINE_EXAMPLES.filter((e) => !q || e.q.toLowerCase().includes(q)).map((e) => ({ ...e, recent: false }));
    const rec = recents.filter((r) => !q || r.toLowerCase().includes(q)).map((r) => ({ q: r, icon: <Clock size={14} />, recent: true }));
    const ex = EXAMPLES.filter((e) => !q || e.q.toLowerCase().includes(q) || q.length < 3).map((e) => ({ ...e, recent: false }));
    const seen = new Set<string>();
    return [...rec, ...ex].filter((i) => (seen.has(i.q) ? false : (seen.add(i.q), true))).slice(0, 6);
  }, [query, recents, refining]);

  const open = !loading && (focused || (idle && !query)) && items.length > 0;

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setFocused(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function submit(q: string) {
    const v = q.trim();
    if (!v) return;
    setQuery(v);
    setFocused(false);
    setActive(-1);
    inputRef.current?.blur();
    if (!refining) pushRecent(v);
    onSearch(v);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocused(true);
      setActive((a) => Math.min(items.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(-1, a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      submit(active >= 0 && items[active] ? items[active].q : query);
    } else if (e.key === "Escape") {
      setFocused(false);
      setActive(-1);
    }
  }

  return (
    <div ref={wrapRef} className="pointer-events-auto relative w-full">
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="glass-strong absolute inset-x-0 bottom-full mb-3 overflow-hidden rounded-2xl p-1.5"
          >
            <li className="px-3 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{refining ? "Refine or ask" : query ? "Suggestions" : "Try one of these"}</li>
            {items.map((it, i) => (
              <motion.li
                key={it.q}
                role="option"
                aria-selected={i === active}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0, transition: { delay: 0.03 * i } }}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  submit(it.q);
                }}
                className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] transition-colors ${i === active ? "bg-teal-400/12 text-slate-50" : "text-slate-300"}`}
              >
                <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg ${it.recent ? "bg-white/[0.05] text-slate-400" : "bg-teal-400/10 text-teal-300"}`}>{it.icon}</span>
                <span className="min-w-0 flex-1 truncate">{it.q}</span>
                {i === active && <span className="hidden text-[10px] text-slate-500 sm:inline">↵ Enter</span>}
              </motion.li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>

      <motion.form
        layout
        onSubmit={(e) => {
          e.preventDefault();
          submit(query);
        }}
        className={`glass-strong relative flex items-center gap-2 rounded-2xl p-2 pl-4 transition-shadow ${focused ? "shadow-[0_0_0_1px_rgba(226, 251, 92,0.45),0_20px_60px_-20px_rgba(226, 251, 92,0.35)]" : ""}`}
      >
        {loading && (
          <span className="pointer-events-none absolute inset-0 overflow-hidden rounded-2xl">
            <motion.span className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-teal-300/15 to-transparent" initial={{ x: "-100%" }} animate={{ x: "300%" }} transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }} />
          </span>
        )}
        <Sparkles size={18} className="shrink-0 text-teal-300" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(-1);
          }}
          onFocus={() => setFocused(true)}
          onKeyDown={onKey}
          placeholder={refining ? "Ask what's nearby, or refine: bigger, cheaper, near transit…" : "What do you want to open, and where?"}
          aria-label={refining ? "Refine the search or ask about the matches" : "Describe your business and location"}
          className="min-w-0 flex-1 bg-transparent py-2 text-[15px] text-slate-50 placeholder:text-slate-500 focus:outline-none"
        />
        {query && !loading && (
          <button type="button" onClick={() => (setQuery(""), inputRef.current?.focus())} className="rounded-lg p-1.5 text-slate-500 hover:text-slate-200" aria-label="Clear">
            <X size={16} />
          </button>
        )}
        <motion.button
          whileTap={{ scale: 0.94 }}
          type="submit"
          disabled={loading || !query.trim()}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-teal-300 to-cyan-400 text-ink-950 shadow-lg shadow-teal-500/25 transition-opacity disabled:opacity-40"
          aria-label="Search"
        >
          {loading ? <Spinner className="h-4 w-4 text-ink-950" /> : query.trim() ? <ArrowUp size={18} strokeWidth={2.5} /> : <Search size={17} strokeWidth={2.5} />}
        </motion.button>
      </motion.form>
    </div>
  );
}
