"use client";

import { notFound } from "next/navigation";
import { useState } from "react";
import type { Analysis, AnalysisEvent, AnalysisResult } from "@/lib/api-types";
import sample from "@/lib/sample-analysis.json";
import AnalysisView from "@/components/analysis/AnalysisView";

/**
 * Dev-only preview of the dashboard rendered from lib/sample-analysis.json, so the UI can be
 * designed and screenshotted without the backend or the LLM. Disabled in production builds.
 */
const EVENTS: AnalysisEvent[] = [
  { t: 0, agent: "engine", type: "plan", message: "Restaurant query → running Vexcel, Neighborhood, Compliance in parallel; Cost after; Matterport skipped (no tour)" },
  { t: 0.4, agent: "matterport", type: "skipped", message: "No Matterport model linked to this property" },
  { t: 0.5, agent: "vexcel", type: "start", message: "Investigating building for a 40-seat restaurant" },
  { t: 3.1, agent: "vexcel", type: "tool_call", message: "get_building_profile()" },
  { t: 6.8, agent: "vexcel", type: "tool_call", message: "get_field_group(group='roof-objects')" },
  { t: 7.0, agent: "vexcel", type: "tool_result", message: "E2 · 0 AC units detected — treat HVAC as unknown" },
  { t: 0.5, agent: "neighborhood", type: "start", message: "Choosing a radius for a downtown restaurant" },
  { t: 5.2, agent: "neighborhood", type: "tool_call", message: "find_nearby_places(category='competitors', radius_m=500)" },
  { t: 0.6, agent: "compliance", type: "start", message: "Checking Houston rules for restaurant use" },
  { t: 4.0, agent: "compliance", type: "tool_call", message: "compute_parking_requirement(sqft=5212, use='restaurant')" },
  { t: 31, agent: "compliance", type: "done", message: "6 rule checks · 5 tool calls" },
  { t: 38, agent: "vexcel", type: "done", message: "3 findings · 5 tool calls" },
  { t: 44, agent: "neighborhood", type: "done", message: "3 findings · 6 tool calls" },
  { t: 45, agent: "cost", type: "start", message: "Estimating costs using Vexcel + compliance findings" },
  { t: 66, agent: "cost", type: "done", message: "Fit-out $512k–$968k" },
  { t: 67, agent: "engine", type: "followup", message: "Parking conflict → asking Compliance about market-based area" },
  { t: 74, agent: "engine", type: "validation", message: "All 11 findings cite existing evidence" },
  { t: 80, agent: "engine", type: "done", message: "Score 68 · confidence 74% · Recommended with conditions" },
];

export default function DemoAnalysisPage() {
  const [analysis] = useState<Analysis>(() => ({
    id: "demo",
    status: "completed",
    created_at: new Date().toISOString(),
    query: "I want to open a 40-seat restaurant in Houston",
    intent: {
      business_type: "restaurant",
      business_label: "Restaurant",
      location_text: "Houston",
      seats: 40,
      sqft: null,
      requirements: [],
      budget: null,
      parser: "rules",
    },
    property: {
      id: "vx_demo",
      lat: 29.75752,
      lon: -95.36546,
      footprint: {
        type: "Polygon",
        coordinates: [
          [
            [-95.3655688, 29.7570853],
            [-95.3649539, 29.7574505],
            [-95.3653512, 29.7579547],
            [-95.3659661, 29.7575895],
            [-95.3655688, 29.7570853],
          ],
        ],
      },
      parcel: null,
      building_type: "commercial",
      area_sqft: 5212,
      roof_condition: 4.0,
      roof_condition_label: "Good",
      stories_est: 1,
      match_score: 78,
      match_reasons: ["Commercial building", "Size fits 40 seats"],
      source: "vexcel",
      address: "901 McKinney St, Downtown Houston",
      key_facts: [],
      raw: null,
      imagery: { collection: "us-tx-houston-2026", date: "2025-12-31", gsd_m: 0.074 },
    },
    radius_m: 500,
    events: EVENTS,
    result: sample as unknown as AnalysisResult,
    error: null,
  }));
  if (process.env.NODE_ENV === "production") notFound();
  return <AnalysisView analysis={analysis} demo />;
}
