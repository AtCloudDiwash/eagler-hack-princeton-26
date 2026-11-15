/** Small GeoJSON helpers for the MapLibre layers. */
import type { GeoJSONGeometry } from "./api-types";

export type LngLat = [number, number];
export type FC = GeoJSON.FeatureCollection;

export const EMPTY_FC: FC = { type: "FeatureCollection", features: [] };

export function asGeometry(g: GeoJSONGeometry | null | undefined): GeoJSON.Geometry | null {
  if (!g || !g.coordinates) return null;
  if (g.type === "Polygon" || g.type === "MultiPolygon" || g.type === "Point") return g as unknown as GeoJSON.Geometry;
  return null;
}

/** Approximate circle polygon (meters) for radius rings. */
export function circlePolygon(center: LngLat, radiusM: number, steps = 96): GeoJSON.Feature<GeoJSON.Polygon> {
  const [lon, lat] = center;
  const coords: LngLat[] = [];
  const dLat = radiusM / 110_574;
  const dLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    coords.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coords] } };
}

export function boundsOf(points: LngLat[]): [LngLat, LngLat] | null {
  if (points.length === 0) return null;
  let [w, s] = points[0];
  let [e, n] = points[0];
  for (const [x, y] of points) {
    w = Math.min(w, x);
    e = Math.max(e, x);
    s = Math.min(s, y);
    n = Math.max(n, y);
  }
  return [
    [w, s],
    [e, n],
  ];
}

export const heightFor = (stories: number | null | undefined) => (stories && stories > 0 ? stories * 4 : 8);
