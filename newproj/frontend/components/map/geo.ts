import type { LatLngExpression } from "leaflet";
import type { GeoJSONGeometry } from "@/lib/api-types";

/** GeoJSON Polygon / MultiPolygon ([lon, lat]) -> Leaflet polygon positions ([lat, lon]). */
export function toPositions(geom: GeoJSONGeometry | null | undefined): LatLngExpression[][][] {
  if (!geom || !geom.coordinates) return [];
  const ring = (r: number[][]): LatLngExpression[] => r.map(([lon, lat]) => [lat, lon] as [number, number]);
  try {
    if (geom.type === "Polygon") return [(geom.coordinates as number[][][]).map(ring)];
    if (geom.type === "MultiPolygon") return (geom.coordinates as number[][][][]).map((poly) => poly.map(ring));
  } catch {
    return [];
  }
  return [];
}

export const hasShape = (geom: GeoJSONGeometry | null | undefined) =>
  !!geom && (geom.type === "Polygon" || geom.type === "MultiPolygon") && toPositions(geom).length > 0;
