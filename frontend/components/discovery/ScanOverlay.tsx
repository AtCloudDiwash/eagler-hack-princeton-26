"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

const STAGES = ["Understanding your request", "Locating the area", "Scanning Vexcel parcels", "Ranking buildings for your business"];

/** Radar sweep shown over the map while discovery runs. */
export default function ScanOverlay({ active }: { active: boolean }) {
  const [stage, setStage] = useState(0);
  useEffect(() => {
    if (!active) return;
    setStage(0);
    const t = setInterval(() => setStage((s) => Math.min(STAGES.length - 1, s + 1)), 1500);
    return () => clearInterval(t);
  }, [active]);

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.5 } }}
          className="pointer-events-none absolute inset-0 z-10 grid place-items-center"
        >
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(11,18,32,0)_0%,rgba(11,18,32,0.55)_70%)]" />
          <div className="relative h-[min(68vw,380px)] w-[min(68vw,380px)]">
            <div className="absolute inset-0 rounded-full border border-teal-300/35 shadow-[0_0_60px_rgba(212, 245, 58,0.15)_inset]" />
            <span className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-teal-300 shadow-[0_0_20px_#e2fb5c]" />
            <div className="absolute inset-[18%] rounded-full border border-teal-300/15" />
            <div className="absolute inset-[36%] rounded-full border border-teal-300/10" />
            <div className="radar-sweep absolute inset-0 rounded-full" />
            {[0, 0.8, 1.6].map((d) => (
              <span key={d} className="radar-ping absolute inset-0 rounded-full border-2 border-cyan-300/50" style={{ animationDelay: `${d}s` }} />
            ))}
            {[
              [22, 30],
              [68, 24],
              [74, 66],
              [34, 72],
              [52, 46],
            ].map(([x, y], i) => (
              <motion.span
                key={i}
                className="absolute h-2 w-2 rounded-full bg-teal-300 shadow-[0_0_12px_#e2fb5c]"
                style={{ left: `${x}%`, top: `${y}%` }}
                initial={{ opacity: 0, scale: 0 }}
                animate={{ opacity: [0, 1, 0.3], scale: [0, 1.4, 1] }}
                transition={{ delay: 0.6 + i * 0.45, duration: 1.2, repeat: Infinity, repeatDelay: 1.6 }}
              />
            ))}
          </div>
          <div className="glass absolute top-[calc(50%+min(34vw,190px)+16px)] rounded-2xl px-5 py-3 text-center">
            <AnimatePresence mode="wait">
              <motion.div key={stage} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="text-sm font-medium text-slate-100">
                {STAGES[stage]}…
              </motion.div>
            </AnimatePresence>
            <div className="mt-1 text-[11px] text-slate-400">Vexcel aerial AI · OpenStreetMap · your query</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
