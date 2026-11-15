"use client";

import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, ChevronUp, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ChatTurn, MapInteraction, Place } from "@/lib/api-types";
import { fmtDistance } from "@/lib/format";
import { placeMeta } from "@/lib/places";
import { Spinner } from "@/components/ui/primitives";

type Props = {
  turns: ChatTurn[];
  thinking: boolean;
  onNewSearch: () => void;
  onPlace?: (place: Place) => void; // a result card was clicked: focus it and make it the anchor
  onSuggest?: (text: string) => void; // a follow-up chip was tapped
  activePlaceId?: string | null;
  onHoverPlace?: (id: string | null) => void; // highlight the matching pin while a card is hovered
  context?: ReactNode; // the Around · Within · Showing chips, shown in the header
};

const INTERACTION_LABEL: Record<MapInteraction, string> = {
  find_nearby: "Nearby",
  find_nearest: "Nearest",
  find_by_description: "Imagery search",
  explore_surroundings: "Surroundings",
  inspect: "Inspect",
  adjust_results: "Adjusted",
  control_view: "Map view",
  back: "Back",
};

/** The refine-as-you-go conversation above the search bar: the user keeps talking to the agent until the
 *  matches look right, then picks a building and analyzes it. */
export default function RefineThread({ turns, thinking, onNewSearch, onPlace, onSuggest, activePlaceId, onHoverPlace, context }: Props) {
  const [open, setOpen] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length, thinking, open]);
  if (!turns.length) return null;

  return (
    <div className="glass-strong pointer-events-auto mb-2 overflow-hidden rounded-2xl">
      <div className="flex items-center gap-2 border-b border-white/[0.05] px-2.5 py-1.5">
        <button onClick={() => setOpen((o) => !o)} className="flex shrink-0 items-center gap-1 text-slate-400 hover:text-slate-200" title={open ? "Collapse the conversation" : "Show the conversation"}>
          <Sparkles size={12} className="text-teal-300" />
          {open ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
        </button>
        <div className="min-w-0 flex-1">{context}</div>
        <button onClick={onNewSearch} className="flex shrink-0 items-center gap-1 text-[10.5px] text-slate-500 hover:text-teal-300" title="Clear this conversation and start a new search">
          <RotateCcw size={11} /> New
        </button>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="max-h-[150px] space-y-1.5 overflow-y-auto px-3 py-2">
              {turns.map((t, i) =>
                t.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <p className="max-w-[85%] rounded-xl rounded-br-sm bg-teal-400/12 px-2.5 py-1.5 text-[12px] leading-snug text-slate-100">{t.text}</p>
                  </div>
                ) : (
                  <div key={i} className="max-w-[96%]">
                    <p className="text-[12px] leading-snug text-slate-300">
                      {t.interaction && t.interaction !== "back" && (
                        <span className="mr-1.5 rounded bg-teal-400/10 px-1 py-px align-[1px] text-[9.5px] font-semibold uppercase tracking-wider text-teal-300">{INTERACTION_LABEL[t.interaction]}</span>
                      )}
                      {t.text}
                    </p>
                    {!!t.places?.length && (
                      <div className="mt-1 flex gap-1 overflow-x-auto pb-0.5 pr-6 [mask-image:linear-gradient(to_right,black_88%,transparent)]">
                        {t.places.map((pl) => (
                          <button
                            key={pl.id}
                            onClick={() => onPlace?.(pl)}
                            onMouseEnter={() => onHoverPlace?.(pl.id)}
                            onMouseLeave={() => onHoverPlace?.(null)}
                            className={`flex shrink-0 items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left ring-1 ring-inset transition ${activePlaceId === pl.id ? "bg-teal-400/12 ring-teal-300/50" : "bg-white/[0.04] ring-white/[0.07] hover:bg-white/[0.08]"}`}
                            title="Show on the map and ask about it"
                          >
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: placeMeta(pl.group).color }} />
                            <span className="max-w-[120px] truncate text-[10.5px] text-slate-100">{pl.name || placeMeta(pl.group).label}</span>
                            <span className="text-[10px] text-slate-500">{fmtDistance(pl.distance_m)}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {i === turns.length - 1 && !thinking && !!t.suggestions?.length && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {t.suggestions.map((sug) => (
                          <button key={sug} onClick={() => onSuggest?.(sug)} className="rounded-full px-2 py-0.5 text-[10.5px] text-teal-200 ring-1 ring-inset ring-teal-300/30 hover:bg-teal-400/10">
                            {sug}
                          </button>
                        ))}
                      </div>
                    )}
                    {!!t.changes?.length && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {t.changes.map((c) => (
                          <span key={c} className="rounded-md bg-white/[0.05] px-1.5 py-0.5 text-[10.5px] text-slate-300 ring-1 ring-inset ring-white/[0.07]">
                            {c}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ),
              )}
              {thinking && (
                <p className="flex items-center gap-2 text-[12px] text-slate-500">
                  <Spinner className="h-3 w-3" /> Working on your request…
                </p>
              )}
              <div ref={endRef} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
