"use client";

import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, ChevronUp, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ChatTurn } from "@/lib/api-types";
import { Spinner } from "@/components/ui/primitives";

type Props = {
  turns: ChatTurn[];
  thinking: boolean;
  onNewSearch: () => void;
};

/** The refine-as-you-go conversation above the search bar: the user keeps talking to the agent until the
 *  matches look right, then picks a building and analyzes it. */
export default function RefineThread({ turns, thinking, onNewSearch }: Props) {
  const [open, setOpen] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length, thinking, open]);
  if (!turns.length) return null;

  return (
    <div className="glass-strong pointer-events-auto mb-2 overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between px-3 pb-1 pt-2">
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 hover:text-slate-200">
          <Sparkles size={11} className="text-teal-300" /> Refine with the agent
          {open ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
        </button>
        <button onClick={onNewSearch} className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-teal-300" title="Clear this conversation and start a new search">
          <RotateCcw size={11} /> New search
        </button>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="max-h-[170px] space-y-1.5 overflow-y-auto px-3 pb-2.5">
              {turns.map((t, i) =>
                t.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <p className="max-w-[85%] rounded-xl rounded-br-sm bg-teal-400/12 px-2.5 py-1.5 text-[12px] leading-snug text-slate-100">{t.text}</p>
                  </div>
                ) : (
                  <div key={i} className="max-w-[92%]">
                    <p className="text-[12px] leading-snug text-slate-300">{t.text}</p>
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
                  <Spinner className="h-3 w-3" /> Updating your search…
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
