"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Analysis } from "@/lib/api-types";
import Dashboard from "./Dashboard";
import { EvidenceProvider } from "./EvidenceContext";
import InvestigationStage from "./InvestigationStage";

type Phase = "investigating" | "dashboard" | "replay";

/** Live investigation → completion reveal → dashboard; completed analyses can replay the investigation. */
export default function AnalysisView({ analysis, demo = false }: { analysis: Analysis; demo?: boolean }) {
  const completedAtLoad = useRef(analysis.status === "completed" && !!analysis.result);
  const [phase, setPhase] = useState<Phase>(completedAtLoad.current ? "dashboard" : "investigating");

  // A failed analysis that has no result stays on the stage (it shows the error).
  useEffect(() => {
    if (analysis.status === "completed" && analysis.result && completedAtLoad.current && phase === "investigating") setPhase("dashboard");
  }, [analysis.status, analysis.result, phase]);

  const toDashboard = useCallback(() => {
    setPhase("dashboard");
    window.scrollTo({ top: 0 });
  }, []);

  return (
    <EvidenceProvider evidence={analysis.result?.evidence ?? []}>
      <AnimatePresence mode="wait">
        {phase === "dashboard" && analysis.result ? (
          <motion.div key="dash" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.4 }}>
            <Dashboard analysis={analysis} demo={demo} onReplay={analysis.events.length ? () => setPhase("replay") : undefined} />
          </motion.div>
        ) : (
          <motion.div key={phase} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, scale: 1.02 }} transition={{ duration: 0.5 }}>
            <InvestigationStage analysis={analysis} mode={phase === "replay" ? "replay" : "live"} onDone={toDashboard} onExit={phase === "replay" ? toDashboard : undefined} />
          </motion.div>
        )}
      </AnimatePresence>
    </EvidenceProvider>
  );
}
