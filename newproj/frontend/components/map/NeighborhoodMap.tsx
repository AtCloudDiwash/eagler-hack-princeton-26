"use client";

import "leaflet/dist/leaflet.css";
import { useState } from "react";
import { Circle, CircleMarker, MapContainer, Polygon, Tooltip, ZoomControl } from "react-leaflet";
import type { GeoJSONGeometry, Neighborhood } from "@/lib/api-types";
import { buildingColor, colorFor, fmtSqft, titleCase } from "@/lib/format";
import BaseLayers from "./BaseLayers";
import { type BaseLayer, LayerToggle } from "./LayerToggle";
import { hasShape, toPositions } from "./geo";

type Props = {
  neighborhood: Neighborhood;
  selected: { lat: number; lon: number; footprint: GeoJSONGeometry | null; label: string };
  hiddenGroups?: Set<string>;
};

/** Dashboard map: the analyzed building, its radius, neighbors and nearby places. */
export default function NeighborhoodMap({ neighborhood, selected, hiddenGroups }: Props) {
  const [layer, setLayer] = useState<BaseLayer>("aerial");
  const r = neighborhood.radius_m;
  const zoom = r > 1000 ? 14 : r > 500 ? 15 : r > 250 ? 16 : 17;
  return (
    <div className="relative h-full w-full">
      <MapContainer center={[selected.lat, selected.lon]} zoom={zoom} maxZoom={21} zoomControl={false} scrollWheelZoom={false} className="h-full w-full">
        <BaseLayers layer={layer} />
        <ZoomControl position="bottomright" />
        <Circle
          center={[selected.lat, selected.lon]}
          radius={r}
          interactive={false}
          pathOptions={{ color: "#2dd4bf", weight: 1.5, dashArray: "6 6", fillColor: "#2dd4bf", fillOpacity: 0.05 }}
        />
        {neighborhood.buildings.map((b) =>
          hasShape(b.footprint) ? (
            toPositions(b.footprint).map((poly, i) => (
              <Polygon key={`${b.id}-${i}`} positions={poly} pathOptions={{ color: buildingColor(b.building_type), weight: 1, fillOpacity: 0.14 }}>
                <Tooltip sticky>
                  {titleCase(b.building_type) || "Building"} · {fmtSqft(b.area_sqft)}
                </Tooltip>
              </Polygon>
            ))
          ) : (
            <CircleMarker key={b.id} center={[b.lat, b.lon]} radius={3} pathOptions={{ color: buildingColor(b.building_type), weight: 1 }} />
          ),
        )}
        {neighborhood.places
          .filter((p) => !hiddenGroups?.has(p.group))
          .map((p) => (
            <CircleMarker key={p.id} center={[p.lat, p.lon]} radius={4.5} pathOptions={{ color: "#0b1220", weight: 1, fillColor: colorFor(p.group), fillOpacity: 0.95 }}>
              <Tooltip direction="top" offset={[0, -4]}>
                <b>{p.name || titleCase(p.category)}</b>
                <br />
                {p.group} · {Math.round(p.distance_m)} m away
              </Tooltip>
            </CircleMarker>
          ))}
        {hasShape(selected.footprint) &&
          toPositions(selected.footprint).map((poly, i) => (
            <Polygon key={`sel-${i}`} positions={poly} pathOptions={{ color: "#f43f5e", weight: 3, fillColor: "#f43f5e", fillOpacity: 0.3 }}>
              <Tooltip sticky>{selected.label}</Tooltip>
            </Polygon>
          ))}
        <CircleMarker center={[selected.lat, selected.lon]} radius={8} pathOptions={{ color: "#0b1220", weight: 2, fillColor: "#f43f5e", fillOpacity: 1 }}>
          <Tooltip direction="top">{selected.label}</Tooltip>
        </CircleMarker>
      </MapContainer>
      <LayerToggle layer={layer} onChange={setLayer} className="absolute left-3 top-3 z-[1000]" />
    </div>
  );
}
