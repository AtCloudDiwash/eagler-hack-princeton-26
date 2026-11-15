"use client";

import { AnimatePresence, motion } from "motion/react";
import { History, Radius, RotateCcw, Scale } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { BusinessTypeInfo, Candidate, ChatTurn, Neighborhood, PropertyDetail, SearchResponse } from "@/lib/api-types";
import { buildingColor, fmtDistance, fmtFootprint } from "@/lib/format";
import { heightFor, type LngLat } from "@/lib/geo";
import { useMedia } from "@/lib/useMedia";
import type { MapBuilding } from "@/components/map/TurnkeyMap";
import { Brand, HealthDots, LayerToggle, Stepper } from "@/components/shell/Shell";
import SearchDock from "@/components/discovery/SearchDock";
import ScanOverlay from "@/components/discovery/ScanOverlay";
import CandidateRail, { candidateTitle } from "@/components/discovery/CandidateRail";
import PropertySheet from "@/components/discovery/PropertySheet";
import HistoryDrawer from "@/components/discovery/HistoryDrawer";
import RefineThread from "@/components/discovery/RefineThread";

const TurnkeyMap = dynamic(() => import("@/components/map/TurnkeyMap"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 bg-ink-950" />,
});

const SESSION_KEY = "turnkey:discovery";
type Saved = { query: string; result: SearchResponse; selectedId: string | null; radius: number | null; turns?: ChatTurn[] };

/** What the agent says after a search: what it found and that the user can keep refining. */
function foundMessage(r: SearchResponse): string {
  const size = r.program ? ` (~${r.program.size.target_sqft.toLocaleString()} sq ft)` : "";
  const where = r.location?.name ? ` near ${r.location.name.split(",")[0]}` : "";
  const listed = r.candidates.filter((c) => c.best_space).length;
  if (!r.candidates.length) return `I couldn't find buildings for a ${r.intent.business_label.toLowerCase()}${where}. Try another area or a different size.`;
  return `Found ${r.candidates.length} buildings for a ${r.intent.business_label.toLowerCase()}${size}${where}` + (listed ? `, ${listed} with a space listed in your size range` : "") +
    ". Tell me what to change (size, budget, area, must-haves) or ask about them. When one looks right, open it and analyze.";
}

/** The matches the agent can talk about (it never sees more than this). */
function matchSummary(r: SearchResponse): Record<string, unknown>[] {
  return r.candidates.slice(0, 12).map((c) => ({
    title: candidateTitle(c), fit: c.match_score, building_type: c.building_type, stories: c.stories_est,
    listed_space: c.best_space ? { suite: c.best_space.suite, sqft: c.best_space.sqft, floor: c.best_space.floor, rent_per_sqft_yr: c.best_space.rent_per_sqft_yr } : null,
    spaces_on_market: c.space_count, reasons: c.match_reasons.slice(0, 3),
  }));
}

export default function DiscoveryPage() {
  const router = useRouter();
  const desktop = useMedia("(min-width: 640px)");
  const [query, setQuery] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [refineText, setRefineText] = useState("");
  const [refining, setRefining] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [fitKey, setFitKey] = useState<string | null>(null);
  const [riseKey, setRiseKey] = useState<string | null>(null);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [detail, setDetail] = useState<PropertyDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [radius, setRadius] = useState(400);
  const [neighborhood, setNeighborhood] = useState<Neighborhood | null>(null);
  const [nbLoading, setNbLoading] = useState(false);
  const [nbError, setNbError] = useState<string | null>(null);
  const [visibleGroups, setVisibleGroups] = useState<Set<string> | null>(null);

  const [requirements, setRequirements] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const [layer, setLayer] = useState<"aerial" | "map">("aerial");
  const [tilt, setTilt] = useState(false);
  const [focus, setFocus] = useState<{ lat: number; lon: number; zoom?: number; key: string } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const businessTypes = useRef<BusinessTypeInfo[]>([]);
  const searchAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    api
      .businessTypes()
      .then((b) => (businessTypes.current = b))
      .catch(() => {});
  }, []);
  const defaultRadius = useCallback((t: string | undefined) => businessTypes.current.find((b) => b.id === t)?.default_radius_m ?? 400, []);

  const selectCandidate = useCallback(
    (c: Candidate, opts?: { radius?: number }) => {
      setSelected(c);
      setDetail(null);
      setDetailError(null);
      setNeighborhood(null);
      setVisibleGroups(null);
      setAnalyzeError(null);
      setRadius(opts?.radius ?? defaultRadius(result?.intent.business_type));
      const r = opts?.radius ?? defaultRadius(result?.intent.business_type);
      // Frame the building with its neighborhood ring in view.
      setFocus({ lat: c.lat, lon: c.lon, zoom: Math.min(17.2, Math.max(14.6, 16.9 - Math.log2(r / 300))), key: `${c.id}-${Date.now()}` });
    },
    [defaultRadius, result?.intent.business_type],
  );

  // Restore the last search ("Investigate another building").
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as Saved;
      setQuery(saved.query);
      setResult(saved.result);
      setTurns(saved.turns ?? [{ role: "user", text: saved.query }, { role: "agent", text: foundMessage(saved.result) }]);
      setFitKey(`restore-${Date.now()}`);
      const c = saved.result.candidates.find((x) => x.id === saved.selectedId);
      if (c) {
        setSelected(c);
        setRadius(saved.radius ?? 400);
        setFocus({ lat: c.lat, lon: c.lon, zoom: 17.2, key: `restore-${c.id}` });
      }
    } catch {
      /* storage unavailable */
    }
  }, []);
  useEffect(() => {
    if (!result) return;
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ query, result, selectedId: selected?.id ?? null, radius, turns } satisfies Saved));
    } catch {
      /* ignore */
    }
  }, [query, result, selected, radius, turns]);

  async function runSearch(q: string) {
    searchAbort.current?.abort();
    const ctrl = new AbortController();
    searchAbort.current = ctrl;
    setSearching(true);
    setSearchError(null);
    setSelected(null);
    setDetail(null);
    setNeighborhood(null);
    setTurns([{ role: "user", text: q }]);
    try {
      const r = await api.search(q, ctrl.signal);
      setResult(r);
      setTurns([{ role: "user", text: q }, { role: "agent", text: foundMessage(r) }]);
      setFitKey(`${q}-${Date.now()}`);
      setRiseKey(`${q}-${Date.now()}`);
      if (r.candidates.length === 0 && r.location) setFocus({ lat: r.location.lat, lon: r.location.lon, zoom: 14.5, key: `loc-${Date.now()}` });
    } catch (e) {
      if ((e as Error).name !== "AbortError") setSearchError((e as Error).message);
    } finally {
      if (searchAbort.current === ctrl) setSearching(false);
    }
  }

  /** A follow-up on the current results: the agent changes the search (and it re-runs) or answers a question. */
  async function runRefine(message: string) {
    if (!result) return;
    searchAbort.current?.abort();
    const ctrl = new AbortController();
    searchAbort.current = ctrl;
    const history = turns;
    setTurns([...history, { role: "user", text: message }]);
    setRefineText("");
    setRefining(true);
    setSearchError(null);
    try {
      const r = await api.refine({ intent: result.intent, message, history, matches: matchSummary(result) }, ctrl.signal);
      const changes = r.changes.length ? r.changes : undefined;
      if (r.result) {
        setSelected(null);
        setDetail(null);
        setNeighborhood(null);
        setResult(r.result);
        setFitKey(`refine-${Date.now()}`);
        setRiseKey(`refine-${Date.now()}`);
        const count = ` ${r.result.candidates.length} matches now` + (r.result.candidates.some((c) => c.best_space) ? `, ${r.result.candidates.filter((c) => c.best_space).length} with a listed space.` : ".");
        setTurns((t) => [...t, { role: "agent", text: `${r.reply}${count}`, changes }]);
        if (r.result.candidates.length === 0 && r.result.location) setFocus({ lat: r.result.location.lat, lon: r.result.location.lon, zoom: 14.5, key: `loc-${Date.now()}` });
      } else {
        setTurns((t) => [...t, { role: "agent", text: r.reply, changes }]);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setTurns((t) => [...t, { role: "agent", text: `Sorry, that didn't go through (${(e as Error).message}). Try again.` }]);
      }
    } finally {
      if (searchAbort.current === ctrl) setRefining(false);
    }
  }

  useEffect(() => {
    if (!selected) return;
    const ctrl = new AbortController();
    setDetailLoading(true);
    const forRequest = result ? { business_type: result.intent.business_type, sqft: result.program?.size.target_sqft, budget: result.intent.budget } : undefined;
    api
      .property(selected.id, ctrl.signal, forRequest)
      .then(setDetail)
      .catch((e: Error) => e.name !== "AbortError" && setDetailError(e.message))
      .finally(() => !ctrl.signal.aborted && setDetailLoading(false));
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch per building; the request is fixed for a result
  }, [selected]);

  useEffect(() => {
    if (!selected) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      setNbLoading(true);
      setNbError(null);
      api
        .neighborhood(selected.id, radius, ctrl.signal)
        .then(setNeighborhood)
        .catch((e: Error) => e.name !== "AbortError" && setNbError(e.message))
        .finally(() => !ctrl.signal.aborted && setNbLoading(false));
    }, 450);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [selected, radius]);

  async function analyze() {
    if (!selected || !result) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      // The agents get the whole conversation, so refinements ("ground floor only", "$8k a month") reach them too.
      const said = turns.filter((t) => t.role === "user").map((t) => t.text);
      const fullQuery = said.length > 1 ? `${said[0]} (then: ${said.slice(1).join("; ")})` : query;
      const { id } = await api.startAnalysis({ query: fullQuery, intent: result.intent, property_id: selected.id, radius_m: radius, requirements: requirements.trim() || undefined });
      router.push(`/analysis/${id}`);
    } catch (e) {
      setAnalyzeError((e as Error).message);
      setAnalyzing(false);
    }
  }

  /** Start over: clear the search, results, selection, filters and saved session; recenter the map. */
  function resetAll() {
    searchAbort.current?.abort();
    setSearching(false);
    setQuery("");
    setTurns([]);
    setRefineText("");
    setRefining(false);
    setResult(null);
    setSearchError(null);
    setSelected(null);
    setDetail(null);
    setDetailError(null);
    setNeighborhood(null);
    setNbError(null);
    setVisibleGroups(null);
    setHoveredId(null);
    setRequirements("");
    setAnalyzeError(null);
    setAnalyzing(false);
    setRadius(400);
    setFitKey(null);
    setRiseKey(null);
    setTilt(false);
    setFocus({ lat: 29.758, lon: -95.365, zoom: 14.2, key: `reset-${Date.now()}` });
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
  }

  const candidates = useMemo(() => result?.candidates ?? [], [result]);
  const buildings = useMemo<MapBuilding[]>(() => {
    const list: MapBuilding[] = candidates.map((c) => ({ id: c.id, lat: c.lat, lon: c.lon, footprint: c.footprint, height: heightFor(c.stories_est), kind: "candidate" }));
    if (selected && neighborhood) {
      for (const b of neighborhood.buildings) list.push({ id: `nb-${b.id}`, lat: b.lat, lon: b.lon, footprint: b.footprint, height: 7, kind: "neighbor", color: buildingColor(b.building_type) });
    }
    return list;
  }, [candidates, selected, neighborhood]);

  const fitPoints = useMemo<LngLat[]>(() => candidates.map((c) => [c.lon, c.lat]), [candidates]);
  const hovered = candidates.find((c) => c.id === hoveredId && c.id !== selected?.id);
  const padding = desktop
    ? { top: 90, bottom: 130, left: selected ? 60 : 380, right: selected ? 440 : 60 }
    : { top: 80, bottom: selected ? 420 : 260, left: 20, right: 20 };
  const step = !result ? 0 : 1;

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-ink-950">
      <TurnkeyMap
        layer={layer}
        tilt={tilt}
        buildings={buildings}
        places={selected ? neighborhood?.places : undefined}
        visibleGroups={visibleGroups}
        ring={selected ? { center: [selected.lon, selected.lat], radius, color: "#a78bfa" } : null}
        ringKey={selected?.id}
        parcel={selected ? (detail?.parcel ?? selected.parcel) : null}
        riseKey={riseKey}
        hoveredId={hoveredId}
        selectedId={selected?.id ?? null}
        onHover={setHoveredId}
        onSelect={(id) => {
          const c = candidates.find((x) => x.id === id);
          if (c) selectCandidate(c);
        }}
        focus={focus}
        fit={fitKey && !selected ? { points: fitPoints, key: fitKey } : null}
        padding={padding}
        markers={
          hovered
            ? [
                {
                  id: `hover-${hovered.id}`,
                  lon: hovered.lon,
                  lat: hovered.lat,
                  node: (
                    <motion.div initial={{ opacity: 0, y: 6, scale: 0.95 }} animate={{ opacity: 1, y: -14, scale: 1 }} className="glass-strong rounded-xl px-3 py-2 text-left">
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-teal-300">{Math.round(hovered.match_score)}</span>
                        <span className="max-w-[200px] truncate text-xs font-medium text-slate-100">{candidateTitle(hovered)}</span>
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {fmtFootprint(hovered.area_sqft)} · click to inspect
                      </div>
                    </motion.div>
                  ),
                },
              ]
            : []
        }
      />

      <ScanOverlay active={searching} />

      {/* Top bar */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-start justify-between gap-3 p-4">
        <div className="pointer-events-auto glass rounded-2xl px-3 py-2">
          <Brand compact={!desktop} />
        </div>
        <div className="pointer-events-auto absolute left-4 top-[70px] sm:left-1/2 sm:top-4 sm:-translate-x-1/2">
          <Stepper step={step} hint="below" />
        </div>
        <div className="pointer-events-auto flex flex-col items-end gap-2">
          <div className="glass flex items-center gap-1 rounded-2xl p-1.5">
            <span className="hidden px-2 xl:inline">
              <HealthDots />
            </span>
            <button onClick={() => setHistoryOpen(true)} className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white" title="Past analyses">
              <History size={14} /> <span className="hidden lg:inline">History</span>
            </button>
            <Link href="/compare" className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white" title="Compare analyses">
              <Scale size={14} /> <span className="hidden lg:inline">Compare</span>
            </Link>
            <button
              onClick={resetAll}
              disabled={!result && !query && !selected && !searching}
              className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white disabled:opacity-40"
              title="Start over: clear the search, results and selection"
            >
              <RotateCcw size={14} /> <span className="hidden lg:inline">Reset</span>
            </button>
          </div>
          <LayerToggle layer={layer} onChange={setLayer} tilt={tilt} onTilt={setTilt} />
          <AnimatePresence>
            {selected && (
              <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className={`glass w-56 rounded-xl px-3 py-2.5 ${desktop ? "mr-[424px]" : "hidden"}`}>
                <div className="mb-1 flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <Radius size={12} className="text-violet-300" /> Neighborhood
                  </span>
                  <span className="font-mono text-violet-200">{fmtDistance(radius)}</span>
                </div>
                <input type="range" min={100} max={1500} step={50} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="teal-range w-full" aria-label="Neighborhood radius in meters" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Candidates */}
      <AnimatePresence>{result && !selected && !searching && <CandidateRail result={result} hoveredId={hoveredId} onHover={setHoveredId} onSelect={(c) => selectCandidate(c)} />}</AnimatePresence>

      {/* Property sheet */}
      <AnimatePresence>
        {selected && (
          <motion.section
            key="sheet"
            initial={desktop ? { opacity: 0, x: 40 } : { y: "100%" }}
            animate={desktop ? { opacity: 1, x: 0 } : { y: 0 }}
            exit={desktop ? { opacity: 0, x: 40 } : { y: "100%" }}
            transition={{ type: "spring", stiffness: 260, damping: 30 }}
            className={
              desktop
                ? "glass-strong pointer-events-auto absolute bottom-4 right-4 top-[132px] z-30 flex w-[408px] flex-col overflow-hidden rounded-2xl"
                : "glass-strong pointer-events-auto absolute inset-x-0 bottom-0 z-40 flex h-[76dvh] flex-col overflow-hidden rounded-t-3xl"
            }
          >
            {!desktop && (
              <div className="flex items-center justify-between px-4 pt-2">
                <span className="mx-auto h-1 w-10 rounded-full bg-white/20" />
              </div>
            )}
            {!desktop && (
              <div className="px-4 pt-2">
                <div className="mb-1 flex items-center justify-between text-[11px]">
                  <span className="flex items-center gap-1.5 text-slate-300">
                    <Radius size={12} className="text-violet-300" /> Neighborhood
                  </span>
                  <span className="font-mono text-violet-200">{fmtDistance(radius)}</span>
                </div>
                <input type="range" min={100} max={1500} step={50} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="teal-range w-full" aria-label="Neighborhood radius in meters" />
              </div>
            )}
            <div className="min-h-0 flex-1">
            <PropertySheet
              candidate={selected}
              detail={detail}
              detailLoading={detailLoading}
              detailError={detailError}
              onDetailChange={setDetail}
              program={result?.program ?? null}
              neighborhood={neighborhood}
              neighborhoodLoading={nbLoading}
              neighborhoodError={nbError}
              radius={radius}
              visibleGroups={visibleGroups}
              setVisibleGroups={setVisibleGroups}
              requirements={requirements}
              setRequirements={setRequirements}
              onAnalyze={analyze}
              analyzing={analyzing}
              analyzeError={analyzeError}
              onBack={() => {
                setSelected(null);
                setNeighborhood(null);
                setFitKey(`back-${Date.now()}`);
              }}
            />
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      {/* Bottom-center search */}
      <AnimatePresence>
        {(desktop || !selected) && (
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 30 }}
            className={`pointer-events-none absolute inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-5 ${desktop && selected ? "pr-[440px]" : ""}`}
          >
            <div className="w-full max-w-[640px]">
              <AnimatePresence>
                {searchError && (
                  <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="pointer-events-auto mb-2 rounded-xl bg-rose-500/15 px-3 py-2 text-center text-xs text-rose-200 ring-1 ring-rose-400/30">
                    {searchError}
                  </motion.p>
                )}
              </AnimatePresence>
              {!result && !searching && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-3 hidden text-center sm:block">
                  <h1 className="text-2xl font-semibold tracking-tight text-slate-50 drop-shadow">
                    Find the <span className="text-gradient">right building</span> for your business
                  </h1>
                  <p className="mt-1 text-sm text-slate-300/80 drop-shadow">AI agents check the building, the neighborhood, the rules and the cost.</p>
                </motion.div>
              )}
              {result && <RefineThread turns={turns} thinking={refining} onNewSearch={resetAll} />}
              {result ? (
                <SearchDock key="refine" mode="refine" query={refineText} setQuery={setRefineText} onSearch={runRefine} loading={refining || searching} idle={false} />
              ) : (
                <SearchDock key="search" query={query} setQuery={setQuery} onSearch={runSearch} loading={searching} idle={!searching} />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </main>
  );
}
