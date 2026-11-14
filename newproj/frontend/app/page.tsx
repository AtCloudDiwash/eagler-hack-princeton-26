"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { BusinessTypeInfo, Candidate, Neighborhood, PropertyDetail, SearchResponse } from "@/lib/api-types";
import { type BaseLayer, LayerToggle } from "@/components/map/LayerToggle";
import SearchBox from "@/components/discovery/SearchBox";
import IntentBar from "@/components/discovery/IntentBar";
import CandidateList from "@/components/discovery/CandidateList";
import PropertyPanel, { AnalyzeBar } from "@/components/discovery/PropertyPanel";
import HistoryDrawer from "@/components/discovery/HistoryDrawer";
import HealthBadge, { Brand } from "@/components/HealthBadge";
import { Spinner } from "@/components/ui/primitives";

const DiscoveryMap = dynamic(() => import("@/components/map/DiscoveryMap"), {
  ssr: false,
  loading: () => <div className="grid h-full place-items-center text-sm text-slate-500">Loading map…</div>,
});

const SESSION_KEY = "turnkey:discovery";
type Saved = { query: string; result: SearchResponse; selectedId: string | null; radius: number | null };

export default function DiscoveryPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [fitKey, setFitKey] = useState<string | null>(null);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [detail, setDetail] = useState<PropertyDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [radius, setRadius] = useState(400);
  const [neighborhood, setNeighborhood] = useState<Neighborhood | null>(null);
  const [nbLoading, setNbLoading] = useState(false);
  const [nbError, setNbError] = useState<string | null>(null);

  const [requirements, setRequirements] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const [layer, setLayer] = useState<BaseLayer>("aerial");
  const [focus, setFocus] = useState<{ lat: number; lon: number; zoom?: number; key: string } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sheetExpanded, setSheetExpanded] = useState(true);
  const businessTypes = useRef<BusinessTypeInfo[]>([]);
  const searchAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    api
      .businessTypes()
      .then((b) => {
        businessTypes.current = b;
      })
      .catch(() => {});
  }, []);

  const defaultRadius = useCallback((businessType: string | undefined) => {
    return businessTypes.current.find((b) => b.id === businessType)?.default_radius_m ?? 400;
  }, []);

  const selectCandidate = useCallback(
    (c: Candidate, opts?: { radius?: number; fly?: boolean }) => {
      setSelected(c);
      setDetail(null);
      setDetailError(null);
      setNeighborhood(null);
      setAnalyzeError(null);
      setRadius(opts?.radius ?? defaultRadius(result?.intent.business_type));
      setSheetExpanded(true);
      if (opts?.fly !== false) setFocus({ lat: c.lat, lon: c.lon, zoom: 17, key: `${c.id}-${Date.now()}` });
    },
    [defaultRadius, result?.intent.business_type],
  );

  // Restore the last search when coming back from a dashboard ("Investigate another building").
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as Saved;
      setQuery(saved.query);
      setResult(saved.result);
      setFitKey(`restore-${Date.now()}`);
      const c = saved.result.candidates.find((x) => x.id === saved.selectedId);
      if (c) {
        setSelected(c);
        setRadius(saved.radius ?? 400);
      }
    } catch {
      /* storage unavailable or corrupt */
    }
  }, []);

  useEffect(() => {
    if (!result) return;
    try {
      const saved: Saved = { query, result, selectedId: selected?.id ?? null, radius };
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(saved));
    } catch {
      /* ignore */
    }
  }, [query, result, selected, radius]);

  async function runSearch(q: string) {
    searchAbort.current?.abort();
    const ctrl = new AbortController();
    searchAbort.current = ctrl;
    setSearching(true);
    setSearchError(null);
    setSelected(null);
    setDetail(null);
    setNeighborhood(null);
    try {
      const r = await api.search(q, ctrl.signal);
      setResult(r);
      setFitKey(`${q}-${Date.now()}`);
      if (r.candidates.length === 0 && r.location) setFocus({ lat: r.location.lat, lon: r.location.lon, zoom: 15, key: `loc-${Date.now()}` });
      if (r.candidates.length === 1) selectCandidate(r.candidates[0], { radius: defaultRadius(r.intent.business_type) });
    } catch (e) {
      if ((e as Error).name !== "AbortError") setSearchError((e as Error).message);
    } finally {
      if (searchAbort.current === ctrl) setSearching(false);
    }
  }

  // Property detail for the selected candidate.
  useEffect(() => {
    if (!selected) return;
    const ctrl = new AbortController();
    setDetailLoading(true);
    api
      .property(selected.id, ctrl.signal)
      .then(setDetail)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setDetailError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setDetailLoading(false);
      });
    return () => ctrl.abort();
  }, [selected]);

  // Neighborhood, debounced on radius changes.
  useEffect(() => {
    if (!selected) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      setNbLoading(true);
      setNbError(null);
      api
        .neighborhood(selected.id, radius, ctrl.signal)
        .then(setNeighborhood)
        .catch((e: Error) => {
          if (e.name !== "AbortError") setNbError(e.message);
        })
        .finally(() => {
          if (!ctrl.signal.aborted) setNbLoading(false);
        });
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
      const { id } = await api.startAnalysis({
        query,
        intent: result.intent,
        property_id: selected.id,
        radius_m: radius,
        requirements: requirements.trim() || undefined,
      });
      router.push(`/analysis/${id}`);
    } catch (e) {
      setAnalyzeError((e as Error).message);
      setAnalyzing(false);
    }
  }

  function clearAll() {
    setResult(null);
    setSelected(null);
    setQuery("");
    setNeighborhood(null);
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
  }

  const candidates = result?.candidates ?? [];

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-ink-950">
      <div className="absolute inset-0">
        <DiscoveryMap
          layer={layer}
          candidates={candidates}
          selectedId={selected?.id ?? null}
          hoveredId={hoveredId}
          neighborhood={selected ? neighborhood : null}
          radius={selected ? radius : null}
          focus={focus}
          fitKey={fitKey}
          onSelect={(c) => selectCandidate(c, { fly: false })}
          onHover={setHoveredId}
        />
      </div>

      {/* Panel: left column on desktop, bottom sheet on mobile */}
      <section
        className={`absolute inset-x-0 bottom-0 z-[1000] flex flex-col rounded-t-2xl border border-line bg-ink-900/95 shadow-2xl backdrop-blur transition-[max-height] sm:inset-y-3 sm:left-3 sm:right-auto sm:max-h-none sm:w-[440px] sm:rounded-2xl ${
          sheetExpanded ? "max-h-[68dvh]" : "max-h-[9.5rem]"
        }`}
      >
        <button onClick={() => setSheetExpanded((v) => !v)} className="mx-auto mt-1.5 h-1.5 w-10 rounded-full bg-slate-600 sm:hidden" aria-label="Toggle panel" />
        <header className="flex items-center justify-between gap-2 px-4 pb-2 pt-3">
          <Brand />
          <div className="flex items-center gap-1">
            <button onClick={() => setHistoryOpen(true)} className="rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:bg-ink-800 hover:text-teal-300">
              History
            </button>
            {result && (
              <button onClick={clearAll} className="rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:bg-ink-800 hover:text-teal-300">
                New search
              </button>
            )}
          </div>
        </header>
        <div className="px-4 pb-2">
          <HealthBadge />
        </div>
        <div className="px-4 pb-3">
          <SearchBox query={query} setQuery={setQuery} onSearch={runSearch} loading={searching} showExamples={!result && !searching} />
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-4">
          {searching && (
            <div className="flex items-center gap-2 rounded-xl border border-line bg-ink-850/60 p-3 text-xs text-slate-400">
              <Spinner /> Understanding your request and searching Vexcel property data…
            </div>
          )}
          {searchError && <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">{searchError}</p>}

          {!result && !searching && !searchError && <Intro />}

          {result && !searching && (
            <>
              <IntentBar result={result} />
              {selected ? (
                <PropertyPanel
                  candidate={selected}
                  detail={detail}
                  detailLoading={detailLoading}
                  detailError={detailError}
                  radius={radius}
                  setRadius={setRadius}
                  neighborhood={neighborhood}
                  neighborhoodLoading={nbLoading}
                  neighborhoodError={nbError}
                  onBack={() => {
                    setSelected(null);
                    setNeighborhood(null);
                    setFitKey(`back-${Date.now()}`);
                  }}
                  resultCount={candidates.length}
                />
              ) : (
                <CandidateList candidates={candidates} hoveredId={hoveredId} onHover={setHoveredId} onSelect={(c) => selectCandidate(c)} />
              )}
            </>
          )}
        </div>
        {result && selected && !searching && (
          <AnalyzeBar
            requirements={requirements}
            setRequirements={setRequirements}
            onAnalyze={analyze}
            analyzing={analyzing}
            disabled={detailLoading}
            error={analyzeError}
          />
        )}
      </section>

      <LayerToggle layer={layer} onChange={setLayer} className="absolute right-3 top-3 z-[1000]" />
      <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </main>
  );
}

function Intro() {
  const steps = [
    ["Describe", "Tell us your business and city in plain words."],
    ["Discover", "Matching buildings appear on Vexcel aerial imagery."],
    ["Inspect", "Pick one to see its building data and surroundings."],
    ["Decide", "AI agents investigate fit, compliance and cost — with evidence."],
  ];
  return (
    <ol className="grid grid-cols-2 gap-2">
      {steps.map(([t, d], i) => (
        <li key={t} className="rounded-xl border border-line bg-ink-850/50 p-3">
          <div className="text-[10px] font-bold text-teal-400">0{i + 1}</div>
          <div className="text-xs font-semibold text-slate-200">{t}</div>
          <div className="mt-0.5 text-[11px] leading-snug text-slate-500">{d}</div>
        </li>
      ))}
    </ol>
  );
}
