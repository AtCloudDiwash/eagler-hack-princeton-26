"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { Fragment, useEffect, useRef } from "react";
import { Circle, CircleMarker, MapContainer, Polygon, Tooltip, useMap, useMapEvents, ZoomControl } from "react-leaflet";
import type { Candidate, Neighborhood } from "@/lib/api-types";
import { buildingColor, colorFor, fmtSqft, titleCase } from "@/lib/format";
import BaseLayers, { type BaseLayer } from "./BaseLayers";
import { hasShape, toPositions } from "./geo";

type Props = {
  layer: BaseLayer;
  candidates: Candidate[];
  selectedId: string | null;
  hoveredId: string | null;
  neighborhood: Neighborhood | null;
  radius: number | null;
  focus: { lat: number; lon: number; zoom?: number; key: string } | null;
  fitKey: string | null; // changes when a new candidate set should be fitted
  onSelect: (c: Candidate) => void;
  onHover: (id: string | null) => void;
};

const HOUSTON: [number, number] = [29.7604, -95.3698];

function Fitter({ candidates, fitKey }: { candidates: Candidate[]; fitKey: string | null }) {
  const map = useMap();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!fitKey || fitKey === last.current || candidates.length === 0) return;
    last.current = fitKey;
    const pts = candidates.map((c) => [c.lat, c.lon] as [number, number]);
    if (pts.length === 1) map.flyTo(pts[0], 18, { duration: 1 });
    else map.flyToBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 18, duration: 1 });
  }, [candidates, fitKey, map]);
  return null;
}

function Focuser({ focus }: { focus: Props["focus"] }) {
  const map = useMap();
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!focus || focus.key === last.current) return;
    last.current = focus.key;
    map.flyTo([focus.lat, focus.lon], focus.zoom ?? Math.max(map.getZoom(), 17), { duration: 0.9 });
  }, [focus, map]);
  return null;
}

function ClearHover({ onHover }: { onHover: (id: string | null) => void }) {
  useMapEvents({ mouseout: () => onHover(null) });
  return null;
}

export default function DiscoveryMap(props: Props) {
  const { candidates, selectedId, hoveredId, neighborhood, radius } = props;
  const selected = candidates.find((c) => c.id === selectedId) ?? null;

  return (
    <MapContainer center={HOUSTON} zoom={14} maxZoom={21} zoomControl={false} className="h-full w-full">
      <BaseLayers layer={props.layer} />
      <ZoomControl position="bottomright" />

      {/* Neighborhood overlay for the selected building */}
      {selected && radius && (
        <Circle
          center={[selected.lat, selected.lon]}
          radius={radius}
          pathOptions={{ color: "#2dd4bf", weight: 1.5, dashArray: "6 6", fillColor: "#2dd4bf", fillOpacity: 0.04 }}
          interactive={false}
        />
      )}
      {neighborhood?.buildings.map((b) =>
        hasShape(b.footprint) ? (
          toPositions(b.footprint).map((poly, i) => (
            <Polygon
              key={`${b.id}-${i}`}
              positions={poly}
              pathOptions={{ color: buildingColor(b.building_type), weight: 1, fillOpacity: 0.12, opacity: 0.7 }}
            >
              <Tooltip sticky>
                {titleCase(b.building_type) || "Building"} · {fmtSqft(b.area_sqft)}
                {b.roof_condition != null ? ` · roof ${b.roof_condition.toFixed(1)}/5` : ""}
              </Tooltip>
            </Polygon>
          ))
        ) : (
          <CircleMarker key={b.id} center={[b.lat, b.lon]} radius={3} pathOptions={{ color: buildingColor(b.building_type), weight: 1, fillOpacity: 0.6 }} />
        ),
      )}
      {neighborhood?.places.map((p) => (
        <CircleMarker
          key={p.id}
          center={[p.lat, p.lon]}
          radius={4}
          pathOptions={{ color: "#0b1220", weight: 1, fillColor: colorFor(p.group), fillOpacity: 0.95 }}
        >
          <Tooltip direction="top" offset={[0, -4]}>
            <b>{p.name || titleCase(p.category)}</b>
            <br />
            {p.group} · {Math.round(p.distance_m)} m
          </Tooltip>
        </CircleMarker>
      ))}

      {/* Candidates */}
      {candidates.map((c, idx) => {
        const isSel = c.id === selectedId;
        const isHover = c.id === hoveredId;
        const color = isSel ? "#f43f5e" : isHover ? "#facc15" : "#22d3ee";
        const handlers = {
          click: () => props.onSelect(c),
          mouseover: () => props.onHover(c.id),
          mouseout: () => props.onHover(null),
        };
        const label = (
          <Tooltip direction="top" sticky>
            <b>#{idx + 1}</b> {titleCase(c.building_type) || "Building"} · {fmtSqft(c.area_sqft)} · match {Math.round(c.match_score)}
          </Tooltip>
        );
        return (
          <Fragment key={c.id}>
            {hasShape(c.footprint) &&
              toPositions(c.footprint).map((poly, i) => (
                <Polygon
                  key={i}
                  positions={poly}
                  eventHandlers={handlers}
                  pathOptions={{ color, weight: isSel ? 3 : 2, fillColor: color, fillOpacity: isSel ? 0.3 : isHover ? 0.28 : 0.16 }}
                >
                  {label}
                </Polygon>
              ))}
            <CircleMarker
              center={[c.lat, c.lon]}
              radius={isSel ? 9 : 7}
              eventHandlers={handlers}
              pathOptions={{ color: "#0b1220", weight: 2, fillColor: color, fillOpacity: 1 }}
            >
              {label}
            </CircleMarker>
          </Fragment>
        );
      })}
      {selected && hasShape(selected.parcel) &&
        toPositions(selected.parcel).map((poly, i) => (
          <Polygon key={`parcel-${i}`} positions={poly} interactive={false} pathOptions={{ color: "#facc15", weight: 1.5, dashArray: "4 4", fill: false }} />
        ))}

      <Fitter candidates={candidates} fitKey={props.fitKey} />
      <Focuser focus={props.focus} />
      <ClearHover onHover={props.onHover} />
    </MapContainer>
  );
}
