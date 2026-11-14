"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import MapGL, { Layer, Marker, NavigationControl, Source, type MapLayerMouseEvent, type MapRef } from "react-map-gl/maplibre";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";
import type { GeoJSONGeometry, Place } from "@/lib/api-types";
import { TILE_URL } from "@/lib/api";
import { asGeometry, boundsOf, circlePolygon, EMPTY_FC, type FC, type LngLat } from "@/lib/geo";
import { PLACE_GROUPS, placeMeta } from "@/lib/places";

export type BaseLayer = "aerial" | "map";

export type MapBuilding = {
  id: string;
  lat: number;
  lon: number;
  footprint: GeoJSONGeometry | null;
  height: number;
  /** candidate: discovery results · subject: the analyzed/selected building · neighbor: context */
  kind: "candidate" | "subject" | "neighbor";
  color?: string;
};

export type MapRing = { center: LngLat; radius: number; color: string };

type Props = {
  layer: BaseLayer;
  buildings?: MapBuilding[];
  places?: Place[];
  visibleGroups?: Set<string> | null; // null = all
  highlightGroups?: string[]; // glowing groups (agent is looking at them)
  ring?: MapRing | null;
  ringKey?: string | number; // change to replay the expand animation
  parcel?: GeoJSONGeometry | null;
  parcelGlow?: boolean;
  scanning?: boolean; // pulse + sonar around the subject building
  shimmerNeighbors?: boolean;
  riseKey?: string | number | null; // change to make candidate buildings rise from the ground
  hoveredId?: string | null;
  selectedId?: string | null;
  onHover?: (id: string | null) => void;
  onSelect?: (id: string) => void;
  focus?: { lon: number; lat: number; zoom?: number; pitch?: number; bearing?: number; key: string | number } | null;
  fit?: { points: LngLat[]; key: string | number } | null;
  padding?: { top: number; bottom: number; left: number; right: number };
  initial?: { lon: number; lat: number; zoom: number; pitch?: number; bearing?: number };
  showControls?: boolean;
  /** 3D: tilted camera + extruded buildings. 2D (default): straight-down view, imagery at full sharpness. */
  tilt?: boolean;
  /** HTML overlays anchored to coordinates (hover cards, labels). */
  markers?: { id: string; lon: number; lat: number; node: ReactNode; anchor?: "bottom" | "center" | "top" }[];
  children?: ReactNode;
};

const STYLE_URL = "https://tiles.openfreemap.org/styles/dark";
const PLACE_COLOR: ExpressionSpecification = [
  "match",
  ["get", "group"],
  ...Object.entries(PLACE_GROUPS).flatMap(([id, m]) => [id, m.color]),
  "#94a3b8",
] as unknown as ExpressionSpecification;

function footprintFeature(b: MapBuilding, extra: Record<string, unknown> = {}): GeoJSON.Feature | null {
  const g = asGeometry(b.footprint);
  const geometry = g && g.type !== "Point" ? g : circlePolygon([b.lon, b.lat], 9, 12).geometry;
  return { type: "Feature", id: b.id, properties: { id: b.id, h: b.height, color: b.color ?? "#d4f53a", ...extra }, geometry };
}

export default function TurnkeyMap(p: Props) {
  const mapRef = useRef<MapRef>(null);
  const [loaded, setLoaded] = useState(false);
  const [beforeLabels, setBeforeLabels] = useState<string | undefined>(undefined);
  const live = useRef(p);
  live.current = p;

  // ---------- data
  const candidates = useMemo<FC>(() => {
    const feats = (p.buildings ?? [])
      .filter((b) => b.kind === "candidate")
      .map((b) => footprintFeature(b, { state: b.id === p.selectedId ? 2 : b.id === p.hoveredId ? 1 : 0 }))
      .filter(Boolean) as GeoJSON.Feature[];
    return { type: "FeatureCollection", features: feats };
  }, [p.buildings, p.selectedId, p.hoveredId]);
  const subjects = useMemo<FC>(
    () => ({ type: "FeatureCollection", features: (p.buildings ?? []).filter((b) => b.kind === "subject").map((b) => footprintFeature(b)).filter(Boolean) as GeoJSON.Feature[] }),
    [p.buildings],
  );
  const neighbors = useMemo<FC>(
    () => ({ type: "FeatureCollection", features: (p.buildings ?? []).filter((b) => b.kind === "neighbor").map((b) => footprintFeature(b)).filter(Boolean) as GeoJSON.Feature[] }),
    [p.buildings],
  );
  const places = useMemo<FC>(() => {
    const vis = p.visibleGroups;
    return {
      type: "FeatureCollection",
      features: (p.places ?? [])
        .filter((pl) => !vis || vis.has(pl.group))
        .map((pl) => ({
          type: "Feature",
          id: pl.id,
          properties: { group: pl.group, name: pl.name ?? placeMeta(pl.group).label, hl: (p.highlightGroups ?? []).includes(pl.group) ? 1 : 0 },
          geometry: { type: "Point", coordinates: [pl.lon, pl.lat] },
        })),
    };
  }, [p.places, p.visibleGroups, p.highlightGroups]);
  const parcel = useMemo<FC>(() => {
    const g = asGeometry(p.parcel ?? null);
    return g ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: g }] } : EMPTY_FC;
  }, [p.parcel]);

  // ---------- camera
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !p.focus) return;
    map.flyTo({
      center: [p.focus.lon, p.focus.lat],
      zoom: p.focus.zoom ?? 17.3,
      pitch: p.tilt ? (p.focus.pitch ?? 58) : 0,
      bearing: p.tilt ? (p.focus.bearing ?? -20) : 0,
      duration: 2200,
      essential: true,
      padding: p.padding,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.focus?.key, loaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !p.fit) return;
    const b = boundsOf(p.fit.points);
    if (!b) return;
    if (p.fit.points.length === 1) {
      map.flyTo({ center: p.fit.points[0], zoom: 16.5, pitch: p.tilt ? 50 : 0, bearing: 0, duration: 1800, padding: p.padding });
      return;
    }
    map.fitBounds(b, { padding: p.padding ?? 80, pitch: p.tilt ? 48 : 0, bearing: p.tilt ? -12 : 0, duration: 2000, maxZoom: 16.8 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.fit?.key, loaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    map.easeTo({ pitch: p.tilt ? 55 : 0, bearing: p.tilt ? -18 : 0, duration: 900 });
  }, [p.tilt, loaded]);

  // High-DPI screens: request tiles one zoom level deeper (256px tiles drawn at 128 CSS px) so aerial
  // imagery stays as sharp as the native Vexcel resolution instead of being upscaled.
  const [tileSize, setTileSize] = useState(256);
  useEffect(() => {
    if (window.devicePixelRatio >= 1.5) setTileSize(128);
  }, []);

  // ---------- animation loop (rise, ring expansion, scan sonar, pulses, shimmer)
  const anim = useRef({ riseStart: 0, ringStart: 0 });
  useEffect(() => {
    anim.current.riseStart = performance.now();
  }, [p.riseKey]);
  useEffect(() => {
    anim.current.ringStart = performance.now();
  }, [p.ringKey, p.ring?.radius]);

  useEffect(() => {
    if (!loaded) return;
    const map = mapRef.current?.getMap();
    if (!map) return;
    let raf = 0;
    const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
    const tick = (now: number) => {
      const cur = live.current;
      // Candidates rise from the ground with a stagger handled by easing on the whole layer.
      const rise = cur.riseKey == null ? 1 : ease((now - anim.current.riseStart) / 1400);
      if (map.getLayer("tk-cand-ext")) map.setPaintProperty("tk-cand-ext", "fill-extrusion-height", ["*", ["get", "h"], rise]);
      // Ring expands to its radius, then breathes.
      const ringSrc = map.getSource("tk-ring") as GeoJSONSource | undefined;
      if (ringSrc && cur.ring) {
        const k = ease((now - anim.current.ringStart) / 1100);
        ringSrc.setData(circlePolygon(cur.ring.center, Math.max(4, cur.ring.radius * k)));
        if (map.getLayer("tk-ring-line")) map.setPaintProperty("tk-ring-line", "line-opacity", 0.55 + 0.35 * Math.sin(now / 420));
      }
      // Sonar around the subject building while an agent inspects it.
      const scanSrc = map.getSource("tk-scan") as GeoJSONSource | undefined;
      const subject = (cur.buildings ?? []).find((b) => b.kind === "subject");
      if (scanSrc) {
        if (cur.scanning && subject) {
          const phase = ((now % 1800) / 1800);
          scanSrc.setData(circlePolygon([subject.lon, subject.lat], 12 + phase * 90, 48));
          if (map.getLayer("tk-scan-line")) map.setPaintProperty("tk-scan-line", "line-opacity", 0.9 * (1 - phase));
        } else {
          scanSrc.setData(EMPTY_FC);
        }
      }
      if (map.getLayer("tk-subj-ext")) {
        const pulse = cur.scanning ? 0.5 + 0.5 * Math.sin(now / 260) : 0;
        map.setPaintProperty("tk-subj-ext", "fill-extrusion-color", pulse > 0 ? `rgb(${Math.round(212 + 43 * pulse)}, ${Math.round(245 + 10 * pulse)}, ${Math.round(58 + 197 * pulse)})` : "#e2fb5c");
      }
      if (map.getLayer("tk-nb-ext")) map.setPaintProperty("tk-nb-ext", "fill-extrusion-opacity", cur.shimmerNeighbors ? 0.3 + 0.28 * Math.sin(now / 300) : 0.28);
      if (map.getLayer("tk-places-glow")) map.setPaintProperty("tk-places-glow", "circle-opacity", 0.35 + 0.35 * Math.sin(now / 280));
      if (map.getLayer("tk-parcel-line")) map.setPaintProperty("tk-parcel-line", "line-opacity", cur.parcelGlow ? 0.55 + 0.45 * Math.sin(now / 300) : 0.65);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [loaded]);

  // ---------- interaction
  const onMove = useCallback((e: MapLayerMouseEvent) => {
    const f = e.features?.[0];
    const id = (f?.properties?.id as string | undefined) ?? null;
    live.current.onHover?.(id);
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = id ? "pointer" : "";
  }, []);
  const onClick = useCallback((e: MapLayerMouseEvent) => {
    const id = e.features?.[0]?.properties?.id as string | undefined;
    if (id) live.current.onSelect?.(id);
  }, []);

  const init = p.initial ?? { lon: -95.3650, lat: 29.7580, zoom: 14.2, pitch: 40, bearing: -12 };
  const aerial = p.layer === "aerial";

  return (
    <MapGL
      ref={mapRef}
      initialViewState={{ longitude: init.lon, latitude: init.lat, zoom: init.zoom, pitch: p.tilt ? (init.pitch ?? 40) : 0, bearing: p.tilt ? (init.bearing ?? 0) : 0 }}
      mapStyle={STYLE_URL}
      maxPitch={75}
      style={{ position: "absolute", inset: 0 }}
      interactiveLayerIds={p.onSelect ? ["tk-cand-ext"] : []}
      onMouseMove={p.onHover ? onMove : undefined}
      onMouseLeave={() => p.onHover?.(null)}
      onClick={onClick}
      attributionControl={{ compact: true }}
      onLoad={(e) => {
        // Imagery goes above every road/area layer of the base style and below the labels only.
        const layers = e.target.getStyle().layers ?? [];
        let lastShape = -1;
        layers.forEach((l, i) => {
          if (l.type !== "symbol") lastShape = i;
        });
        setBeforeLabels(layers.slice(lastShape + 1).find((l) => l.type === "symbol")?.id);
        setLoaded(true);
      }}
    >
      {p.showControls !== false && <NavigationControl position="bottom-right" visualizePitch />}

      {/* Vexcel aerial imagery under the street labels (hybrid look) */}
      <Source key={`vexcel-${tileSize}`} id="vexcel" type="raster" tiles={[TILE_URL]} tileSize={tileSize} maxzoom={21} attribution="Imagery © Vexcel">
        <Layer id="vexcel" type="raster" beforeId={beforeLabels} layout={{ visibility: aerial ? "visible" : "none" }} paint={{ "raster-opacity": 1, "raster-fade-duration": 120, "raster-resampling": "linear" }} />
      </Source>

      {/* City context in 3D on the street map */}
      {loaded && !aerial && (
        <Layer
          id="tk-city-3d"
          type="fill-extrusion"
          source="openmaptiles"
          source-layer="building"
          minzoom={14}
          beforeId={beforeLabels}
          paint={{ "fill-extrusion-color": "#1a2742", "fill-extrusion-height": ["coalesce", ["get", "render_height"], 6], "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0], "fill-extrusion-opacity": 0.75 }}
        />
      )}

      <Source id="tk-parcel" type="geojson" data={parcel}>
        <Layer id="tk-parcel-line" type="line" paint={{ "line-color": "#facc15", "line-width": 2, "line-dasharray": [2, 1.5], "line-opacity": 0.65 }} />
      </Source>

      <Source id="tk-ring" type="geojson" data={p.ring ? circlePolygon(p.ring.center, p.ring.radius) : EMPTY_FC}>
        <Layer id="tk-ring-fill" type="fill" paint={{ "fill-color": p.ring?.color ?? "#d4f53a", "fill-opacity": 0.06 }} />
        <Layer id="tk-ring-line" type="line" paint={{ "line-color": p.ring?.color ?? "#d4f53a", "line-width": 2, "line-opacity": 0.8 }} />
      </Source>

      <Source id="tk-neighbors" type="geojson" data={neighbors}>
        <Layer id="tk-nb-ext" type="fill-extrusion" paint={{ "fill-extrusion-color": ["get", "color"], "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.28 }} />
      </Source>

      <Source id="tk-places" type="geojson" data={places}>
        <Layer id="tk-places-glow" type="circle" filter={["==", ["get", "hl"], 1]} paint={{ "circle-color": PLACE_COLOR, "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 7, 18, 16], "circle-blur": 0.9, "circle-opacity": 0.5 }} />
        <Layer
          id="tk-places-dot"
          type="circle"
          paint={{
            "circle-color": PLACE_COLOR,
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 2.2, 18, 6],
            "circle-stroke-color": "#0a0a0c",
            "circle-stroke-width": 1,
            "circle-opacity": ["case", ["==", ["get", "hl"], 1], 1, 0.75],
          }}
        />
      </Source>

      <Source id="tk-candidates" type="geojson" data={candidates}>
        <Layer
          id="tk-cand-ext"
          type="fill-extrusion"
          paint={{
            "fill-extrusion-color": ["match", ["get", "state"], 2, "#f472b6", 1, "#f7ffd6", "#d4f53a"],
            "fill-extrusion-height": ["get", "h"],
            "fill-extrusion-opacity": 0.88,
          }}
        />
        <Layer
          id="tk-cand-glow"
          type="line"
          filter={[">", ["get", "state"], 0]}
          paint={{ "line-color": ["match", ["get", "state"], 2, "#f472b6", "#e2fb5c"], "line-width": 6, "line-blur": 6, "line-opacity": 0.9 }}
        />
      </Source>

      <Source id="tk-subject" type="geojson" data={subjects}>
        <Layer id="tk-subj-ext" type="fill-extrusion" paint={{ "fill-extrusion-color": "#e2fb5c", "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.92 }} />
        <Layer id="tk-subj-glow" type="line" paint={{ "line-color": "#ecff8f", "line-width": 7, "line-blur": 7, "line-opacity": 0.85 }} />
      </Source>

      <Source id="tk-scan" type="geojson" data={EMPTY_FC}>
        <Layer id="tk-scan-line" type="line" paint={{ "line-color": "#ecff8f", "line-width": 2.5, "line-opacity": 0 }} />
      </Source>

      {(p.markers ?? []).map((m) => (
        <Marker key={m.id} longitude={m.lon} latitude={m.lat} anchor={m.anchor ?? "bottom"} style={{ pointerEvents: "none" }}>
          {m.node}
        </Marker>
      ))}
      {p.children}
    </MapGL>
  );
}
