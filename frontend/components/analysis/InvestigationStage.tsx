"use client";

import { AnimatePresence, motion } from "motion/react";
import { Building2, CheckCircle2, CircleDashed, DollarSign, Landmark, ListTree, Loader2, Orbit, Satellite, Scale, TriangleAlert, X } from "lucide-react";
import dynamic from "next/dynamic";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AgentName, Analysis, AnalysisEvent, Neighborhood } from "@/lib/api-types";
import { AGENT_META, buildingColor, fmtMoney, VERDICT_STYLE } from "@/lib/format";
import { heightFor } from "@/lib/geo";
import { AGENT_ORDER, agentState, COMPLIANCE_CHIPS, eventText, fmtClock, parseUpfront, type AgentState } from "@/lib/humanize";
import { placeMeta } from "@/lib/places";
import { useMedia } from "@/lib/useMedia";
import type { MapBuilding } from "@/components/map/TurnkeyMap";
import { Brand, LayerToggle, Stepper } from "@/components/shell/Shell";
import { AnimatedNumber, Meter, ScoreRing } from "@/components/ui/primitives";

const TurnkeyMap = dynamic(() => import("@/components/map/TurnkeyMap"), { ssr: false, loading: () => <div className="absolute inset-0 bg-ink-950" /> });

const AGENT_ICON: Record<AgentName, ReactNode> = {
  vexcel: <Satellite size={15} />,
  neighborhood: <Building2 size={15} />,
  compliance: <Landmark size={15} />,
  cost: <DollarSign size={15} />,
  matterport: <CircleDashed size={15} />,
  engine: <Orbit size={15} />,
};

type Props = {
  analysis: Analysis;
  mode: "live" | "replay";
  /** Called after the completion reveal (live: analysis finished; replay: playback ended). */
  onDone?: () => void;
  onExit?: () => void;
};

/** The map is the stage: agent tool calls drive map choreography; mission control narrates. */
export default function InvestigationStage({ analysis, mode, onDone, onExit }: Props) {
  const desktop = useMedia("(min-width: 768px)");
  const [layer, setLayer] = useState<"aerial" | "map">("aerial");
  const [tilt, setTilt] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [nb, setNb] = useState<Neighborhood | null>(analysis.result?.neighborhood ?? null);
  const p = analysis.property;
  const allEvents = analysis.events;
  const lastT = allEvents.length ? allEvents[allEvents.length - 1].t : 0;

  // Places + neighbor footprints for the stage (once, cached by the backend).
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .neighborhood(p.id, Math.max(1500, analysis.radius_m), ctrl.signal)
      .then(setNb)
      .catch(() => {});
    return () => ctrl.abort();
  }, [p.id, analysis.radius_m]);

  // ---------- playback clock
  const speed = mode === "replay" ? Math.max(3, lastT / 24) : 1;
  const [playT, setPlayT] = useState(mode === "replay" ? 0 : Infinity);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (mode !== "replay") return;
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const v = ((t - start) / 1000) * speed;
      setPlayT(Math.floor(v * 4) / 4); // 4 updates per playback-second keeps the map cheap
      if (v < lastT + 2) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mode, speed, lastT]);

  const liveFinished = analysis.status === "completed" || analysis.status === "failed";
  useEffect(() => {
    if (mode !== "live" || liveFinished) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [mode, liveFinished]);

  const events = useMemo(() => (mode === "replay" ? allEvents.filter((e) => e.t <= playT) : allEvents), [mode, allEvents, playT]);
  const finished = mode === "replay" ? playT >= lastT + 0.5 : liveFinished;
  const started = new Date(analysis.created_at).getTime();
  // Elapsed: live clock while running; final duration (last event) once finished — never "—".
  const elapsed = mode === "replay" ? Math.min(playT, lastT) : liveFinished ? lastT : Number.isFinite(started) ? (now - started) / 1000 : lastT;

  // ---------- derived agent state
  const byAgent = useMemo(() => {
    const m = new Map<AgentName, AnalysisEvent[]>();
    for (const e of events) {
      if (!m.has(e.agent)) m.set(e.agent, []);
      m.get(e.agent)!.push(e);
    }
    return m;
  }, [events]);
  const states = useMemo(() => {
    const s = {} as Record<AgentName, AgentState>;
    for (const a of [...AGENT_ORDER, "engine" as AgentName]) s[a] = agentState(byAgent.get(a) ?? [], finished);
    return s;
  }, [byAgent, finished]);

  const toolCalls = events.filter((e) => e.type === "tool_call");
  const nbCalls = useMemo(() => (byAgent.get("neighborhood") ?? []).filter((e) => e.type === "tool_call"), [byAgent]);
  const nbLast = nbCalls[nbCalls.length - 1];
  const nbArgs = ((nbLast?.data?.args as Record<string, unknown>) ?? {}) as { radius_m?: number; group?: string };

  // Groups the neighborhood agent has looked at reveal on the map as they are counted.
  const revealedRadius = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of nbCalls) {
      const tool = e.data?.tool;
      const args = (e.data?.args ?? {}) as { group?: string; radius_m?: number };
      const r = typeof args.radius_m === "number" ? args.radius_m : 400;
      const keep = (g: string) => m.set(g, Math.max(m.get(g) ?? 0, r));
      if (tool === "count_places" && args.group) keep(args.group);
      if (tool === "get_access_options") {
        keep("transit");
        keep("parking");
      }
    }
    return m;
  }, [nbCalls]);
  const revealed = useMemo(() => new Set(revealedRadius.keys()), [revealedRadius]);
  // Only the places the agent actually looked at: its groups, inside the radius it chose.
  const stagePlaces = useMemo(() => (nb?.places ?? []).filter((pl) => pl.distance_m <= (revealedRadius.get(pl.group) ?? -1)), [nb, revealedRadius]);
  const latestGroups = useMemo(
    () => (nbLast?.data?.tool === "count_places" && nbArgs.group ? [nbArgs.group] : nbLast?.data?.tool === "get_access_options" ? ["transit", "parking"] : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nbLast?.t],
  );

  const ringRadius = typeof nbArgs.radius_m === "number" ? nbArgs.radius_m : null;
  const vexcelBusy = states.vexcel === "running";
  const complianceBusy = states.compliance === "running";
  const shimmer = states.neighborhood === "running" && nbLast?.data?.tool === "get_building_mix";

  // Place counts discovered so far ("E6: 12 restaurants & cafes within 500 m").
  const placeCounts = useMemo(() => {
    const out: { group: string; n: number; radius: string }[] = [];
    const nbEvents = byAgent.get("neighborhood") ?? [];
    nbEvents.forEach((e, i) => {
      if (e.type !== "tool_call" || e.data?.tool !== "count_places") return;
      const g = String((e.data?.args as Record<string, unknown>)?.group ?? "");
      const label = placeMeta(g).label.toLowerCase();
      // Results carry {tool, args} (newer runs); older runs are matched by the group label in the message.
      const later = nbEvents.slice(i + 1).filter((x) => x.type === "tool_result");
      const res =
        later.find((x) => x.data?.tool === "count_places" && (x.data?.args as Record<string, unknown> | undefined)?.group === g) ??
        later.find((x) => !x.data?.tool && x.message.toLowerCase().includes(label));
      const m = res?.message.match(/E\d+:\s*(\d+)\s.+within\s(\d+\s?m)/);
      if (m && g && !out.some((o) => o.group === g)) out.push({ group: g, n: Number(m[1]), radius: m[2] });
    });
    return out;
  }, [byAgent]);

  // Compliance checklist.
  const checklist = useMemo(() => {
    const ev = byAgent.get("compliance") ?? [];
    const out: { label: string; done: boolean }[] = [];
    ev.forEach((e, i) => {
      if (e.type !== "tool_call") return;
      const label = COMPLIANCE_CHIPS[String(e.data?.tool)] ?? null;
      if (!label || out.some((o) => o.label === label)) return;
      const tool = String(e.data?.tool);
      out.push({ label, done: ev.slice(i + 1).some((x) => (x.type === "tool_result" && (!x.data?.tool || x.data.tool === tool)) || x.type === "done") });
    });
    return out;
  }, [byAgent]);

  const upfront = useMemo(() => {
    const res = [...(byAgent.get("cost") ?? [])].reverse().find((e) => e.type === "tool_result" && /Upfront/.test(e.message));
    return res ? parseUpfront(res.message) : null;
  }, [byAgent]);

  // ---------- camera choreography (follow the agent doing the most visual thing)
  const [focus, setFocus] = useState<{ lon: number; lat: number; zoom: number; pitch: number; bearing: number; key: string } | null>(null);
  const lastMove = useRef(0);
  const camKey = vexcelBusy && !ringRadius ? "roof" : ringRadius ? `ring-${ringRadius}` : "roof";
  useEffect(() => {
    const t = Date.now();
    const go = () => {
      lastMove.current = Date.now();
      const zoom = camKey === "roof" ? 17.6 : Math.max(13.6, 16.6 - Math.log2((ringRadius ?? 250) / 200));
      setFocus({ lon: p.lon, lat: p.lat, zoom, pitch: camKey === "roof" ? 62 : 52, bearing: -25 + (Math.random() * 30 - 15), key: `${camKey}-${t}` });
    };
    const wait = Math.max(0, 2600 - (t - lastMove.current));
    const h = setTimeout(go, wait);
    return () => clearTimeout(h);
  }, [camKey, ringRadius, p.lon, p.lat]);

  // ---------- completion reveal
  const [revealing, setRevealing] = useState(false);
  useEffect(() => {
    if (!finished) return;
    if (mode === "live" && analysis.status !== "completed") return;
    if (!analysis.result) return;
    setRevealing(true);
    const h = setTimeout(() => onDone?.(), mode === "replay" ? 2600 : 3000);
    return () => clearTimeout(h);
  }, [finished, mode, analysis.status, analysis.result, onDone]);

  const buildings = useMemo<MapBuilding[]>(() => {
    const list: MapBuilding[] = [{ id: p.id, lat: p.lat, lon: p.lon, footprint: p.footprint, height: heightFor(p.stories_est), kind: "subject" }];
    for (const b of nb?.buildings ?? []) if (b.id !== p.id) list.push({ id: `nb-${b.id}`, lat: b.lat, lon: b.lon, footprint: b.footprint, height: 7, kind: "neighbor", color: buildingColor(b.building_type) });
    return list;
  }, [nb, p]);

  const agentsShown = AGENT_ORDER.filter((a) => a !== "matterport" || (byAgent.get(a)?.length ?? 0) > 0 || finished);
  const doneCount = agentsShown.filter((a) => ["done", "skipped", "error"].includes(states[a])).length;
  const progress = finished ? 100 : Math.round((doneCount / agentsShown.length) * 90 + Math.min(10, toolCalls.length / 3));
  const engineLine = [...(byAgent.get("engine") ?? [])].reverse().find((e) => ["plan", "followup", "validation", "thinking", "done"].includes(e.type));
  const rec = analysis.result?.recommendation;

  return (
    <div className="relative h-dvh w-full overflow-hidden bg-ink-950">
      <TurnkeyMap
        layer={layer}
        tilt={tilt}
        buildings={buildings}
        places={stagePlaces}
        visibleGroups={revealed}
        highlightGroups={latestGroups}
        ring={ringRadius ? { center: [p.lon, p.lat], radius: ringRadius, color: "#a78bfa" } : null}
        ringKey={nbLast ? `${nbLast.t}` : undefined}
        parcel={p.parcel}
        parcelGlow={complianceBusy}
        scanning={vexcelBusy && !finished}
        shimmerNeighbors={shimmer}
        focus={focus}
        padding={desktop ? { top: 80, bottom: 140, left: 400, right: 40 } : { top: 80, bottom: 320, left: 20, right: 20 }}
        initial={{ lon: p.lon, lat: p.lat, zoom: 15.5, pitch: 50, bearing: -20 }}
        showControls={desktop}
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(11,18,32,0.55)_100%)]" />

      {/* Top bar */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-start justify-between gap-3 p-4">
        <div className="pointer-events-auto glass rounded-2xl px-3 py-2">
          <Brand compact={!desktop} />
        </div>
        <div className="pointer-events-auto absolute left-4 top-[70px] sm:left-1/2 sm:top-4 sm:-translate-x-1/2">
          <Stepper step={finished && revealing ? 3 : 2} hint="below" />
        </div>
        <div className="pointer-events-auto flex flex-col items-end gap-2">
          {mode === "replay" && onExit && (
            <button onClick={onExit} className="glass flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] text-slate-200 hover:text-white">
              <X size={13} /> Skip replay
            </button>
          )}
          <LayerToggle layer={layer} onChange={setLayer} tilt={tilt} onTilt={setTilt} />
        </div>
      </div>

      {/* Mission control */}
      <motion.aside
        initial={desktop ? { opacity: 0, x: -30 } : { opacity: 0, y: 40 }}
        animate={{ opacity: 1, x: 0, y: 0 }}
        transition={{ type: "spring", stiffness: 240, damping: 30 }}
        className={desktop ? "glass-strong absolute left-4 top-20 z-20 w-[360px] rounded-2xl" : "glass-strong absolute inset-x-0 bottom-0 z-20 rounded-t-3xl"}
      >
        <div className="border-b border-white/[0.06] p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-300/80">{mode === "replay" ? `Replay · ${Math.round(speed)}× speed` : "Live investigation"} · {analysis.mode === "quick" ? "Quick" : "Deep report"}</div>
              <h2 className="mt-0.5 text-[15px] font-semibold text-slate-50">{finished ? (analysis.status === "failed" ? "Investigation stopped" : "Investigation complete") : "Agents are investigating"}</h2>
            </div>
            <div className="text-right">
              <div className="font-mono text-xl font-semibold tabular-nums text-slate-50">{fmtClock(elapsed)}</div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500">{toolCalls.length} tool calls</div>
            </div>
          </div>
          <div className="mt-3">
            <Meter value={progress} color="linear-gradient(90deg,#e2fb5c,#e2fb5c,#a78bfa)" />
          </div>
          <AnimatePresence mode="wait">
            {engineLine && (
              <motion.p key={engineLine.t + engineLine.message} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-2 flex items-center gap-1.5 truncate text-[11px] text-slate-400">
                <Orbit size={11} className="shrink-0 text-teal-300" />
                <span className="truncate">{engineLine.type === "followup" || engineLine.type === "validation" ? engineLine.message : eventText(engineLine)}</span>
              </motion.p>
            )}
          </AnimatePresence>
        </div>
        <ul className={`space-y-1 p-2 ${desktop ? "" : "max-h-[34dvh] overflow-y-auto"}`}>
          {agentsShown.map((a) => (
            <AgentRow key={a} agent={a} state={states[a]} line={lineFor(byAgent.get(a) ?? [], states[a])} calls={(byAgent.get(a) ?? []).filter((e) => e.type === "tool_call").length} />
          ))}
        </ul>
        <div className="flex items-center justify-between border-t border-white/[0.06] px-4 py-2.5">
          <button onClick={() => setShowLog(true)} className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-teal-200">
            <ListTree size={12} /> Show full log ({events.length})
          </button>
          <span className="text-[10px] text-slate-600">via local Codex CLI</span>
        </div>
        {analysis.error && <p className="mx-4 mb-3 rounded-lg bg-rose-500/10 p-2.5 text-[11px] text-rose-200 ring-1 ring-rose-400/30">{analysis.error}</p>}
      </motion.aside>

      {/* Live discoveries strip */}
      <div className={`pointer-events-none absolute z-20 flex flex-wrap items-end justify-center gap-2 ${desktop ? "inset-x-0 bottom-6 pl-[380px]" : "inset-x-3 top-20"}`}>
        <AnimatePresence>
          {placeCounts.map((pc) => (
            <motion.div key={pc.group} layout initial={{ opacity: 0, y: 14, scale: 0.9 }} animate={{ opacity: 1, y: 0, scale: 1 }} className="glass flex items-center gap-2 rounded-xl px-3 py-2">
              <i className="h-2.5 w-2.5 rounded-full" style={{ background: placeMeta(pc.group).color, boxShadow: `0 0 10px ${placeMeta(pc.group).color}` }} />
              <span className="text-sm font-semibold tabular-nums text-slate-50">
                <AnimatedNumber value={pc.n} duration={0.9} />
              </span>
              <span className="text-[11px] text-slate-400">
                {placeMeta(pc.group).label.toLowerCase()} · {pc.radius}
              </span>
            </motion.div>
          ))}
          {checklist.length > 0 && (
            <motion.div key="checklist" layout initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="glass flex items-center gap-1.5 rounded-xl px-2.5 py-2">
              <Scale size={13} className="text-pink-300" />
              {checklist.map((c) => (
                <motion.span key={c.label} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] ${c.done ? "bg-emerald-400/15 text-emerald-200" : "bg-white/[0.05] text-slate-300"}`}>
                  {c.done ? <CheckCircle2 size={10} /> : <Loader2 size={10} className="animate-spin" />}
                  {c.label}
                </motion.span>
              ))}
            </motion.div>
          )}
          {(states.cost === "running" || upfront) && (
            <motion.div key="cost" layout initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="glass flex items-center gap-2 rounded-xl px-3 py-2">
              <DollarSign size={14} className="text-amber-300" />
              {upfront ? (
                <span className="text-sm font-semibold tabular-nums text-slate-50">
                  <AnimatedNumber value={upfront.low} format={(n) => fmtMoney(n)} /> – <AnimatedNumber value={upfront.high} format={(n) => fmtMoney(n)} />
                  <span className="ml-1.5 text-[11px] font-normal text-slate-400">upfront</span>
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-[11px] text-slate-300">
                  <Loader2 size={11} className="animate-spin" /> Estimating costs…
                </span>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Full log drawer */}
      <AnimatePresence>
        {showLog && (
          <motion.div className="fixed inset-0 z-[60] flex justify-end bg-black/40 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowLog(false)}>
            <motion.aside initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 280, damping: 32 }} className="glass-strong flex h-full w-full max-w-lg flex-col" onClick={(e) => e.stopPropagation()}>
              <header className="flex items-center justify-between border-b border-white/[0.06] p-4">
                <h3 className="font-semibold text-slate-100">Investigation log</h3>
                <button onClick={() => setShowLog(false)} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06]" aria-label="Close">
                  <X size={16} />
                </button>
              </header>
              <div className="flex-1 space-y-1 overflow-y-auto p-4 font-mono text-[11px]">
                {events.map((e, i) => (
                  <div key={i} className="flex gap-2 leading-snug">
                    <span className="w-10 shrink-0 text-right text-slate-600">{e.t.toFixed(0)}s</span>
                    <span className="w-24 shrink-0 truncate" style={{ color: AGENT_META[e.agent]?.color }}>
                      {AGENT_META[e.agent]?.short ?? e.agent}
                    </span>
                    <span className={`min-w-0 break-words ${e.type === "error" ? "text-rose-300" : e.type === "tool_call" ? "text-cyan-200/90" : "text-slate-300"}`}>{e.message}</span>
                  </div>
                ))}
              </div>
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Completion reveal */}
      <AnimatePresence>
        {revealing && rec && (
          <motion.div className="absolute inset-0 z-50 grid place-items-center bg-ink-950/60 backdrop-blur-md" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div initial={{ scale: 0.85, opacity: 0, y: 20 }} animate={{ scale: 1, opacity: 1, y: 0 }} transition={{ type: "spring", stiffness: 200, damping: 20 }} className="flex flex-col items-center text-center">
              <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-teal-300">Investigation complete · {fmtClock(lastT)}</div>
              <ScoreRing value={rec.score} size={180} color={VERDICT_STYLE[rec.verdict].color} label="suitability" />
              <div className={`mt-4 rounded-full px-4 py-1.5 text-sm font-semibold ${VERDICT_STYLE[rec.verdict].bg} ${VERDICT_STYLE[rec.verdict].text}`}>{rec.label || VERDICT_STYLE[rec.verdict].label}</div>
              <p className="mt-3 max-w-md px-6 text-sm text-slate-300">{rec.headline}</p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      {finished && analysis.status === "failed" && mode === "live" && (
        <div className="absolute inset-x-0 top-[124px] z-40 flex justify-center px-4 sm:top-20">
          <div className="glass-strong flex items-center gap-2 rounded-xl px-4 py-3 text-sm text-rose-200">
            <TriangleAlert size={16} /> {analysis.error ?? "The analysis failed."}
          </div>
        </div>
      )}
    </div>
  );
}

function lineFor(events: AnalysisEvent[], state: AgentState): string {
  if (state === "waiting") return "Waiting for the orchestrator";
  const last = [...events].reverse().find((e) => ["tool_call", "start", "done", "skipped", "error"].includes(e.type));
  if (!last) return "Getting started";
  if (state === "done") {
    const calls = events.filter((e) => e.type === "tool_call").length;
    const done = [...events].reverse().find((e) => e.type === "done");
    const findings = done?.message.match(/(\d+) findings/)?.[1];
    return `Finished · ${calls} checks${findings ? ` · ${findings} findings` : ""}`;
  }
  return eventText(last);
}

const STATE_UI: Record<AgentState, { label: string; cls: string }> = {
  waiting: { label: "Queued", cls: "text-slate-500" },
  running: { label: "Working", cls: "text-teal-300" },
  done: { label: "Done", cls: "text-emerald-300" },
  error: { label: "Failed", cls: "text-rose-300" },
  skipped: { label: "Skipped", cls: "text-slate-500" },
};

function AgentRow({ agent, state, line, calls }: { agent: AgentName; state: AgentState; line: string; calls: number }) {
  const meta = AGENT_META[agent];
  const running = state === "running";
  return (
    <motion.li layout className={`flex items-center gap-3 rounded-xl px-2.5 py-2 ${running ? "bg-white/[0.04]" : ""}`}>
      <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl" style={{ background: `${meta.color}1f`, color: meta.color }}>
        {running && <motion.span className="absolute inset-0 rounded-xl" style={{ boxShadow: `0 0 0 2px ${meta.color}` }} animate={{ opacity: [0.9, 0.1, 0.9], scale: [1, 1.12, 1] }} transition={{ duration: 1.6, repeat: Infinity }} />}
        {state === "done" ? <CheckCircle2 size={16} /> : AGENT_ICON[agent]}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-medium text-slate-100">{meta.short}</span>
          <span className={`flex items-center gap-1 text-[10px] ${STATE_UI[state].cls}`}>
            {running && <Loader2 size={10} className="animate-spin" />}
            {STATE_UI[state].label}
            {calls > 0 && <span className="text-slate-600">· {calls}</span>}
          </span>
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={line} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.2 }} className="truncate text-[11px] text-slate-400">
            {line}
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.li>
  );
}
