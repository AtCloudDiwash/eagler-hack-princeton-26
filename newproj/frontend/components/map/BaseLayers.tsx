"use client";

import { TileLayer } from "react-leaflet";
import { TILE_URL } from "@/lib/api";

import type { BaseLayer } from "./LayerToggle";

export type { BaseLayer };

/**
 * Street map (OSM, darkened) always underneath so areas outside Vexcel coverage still render;
 * Vexcel aerial imagery (proxied by the backend so the key never reaches the browser) on top.
 */
export default function BaseLayers({ layer }: { layer: BaseLayer }) {
  return (
    <>
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        className="osm-dark"
        maxNativeZoom={19}
        maxZoom={21}
      />
      {layer === "aerial" && <TileLayer url={TILE_URL} attribution="Imagery &copy; Vexcel" maxNativeZoom={21} maxZoom={21} />}
    </>
  );
}
