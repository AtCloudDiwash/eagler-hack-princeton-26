/** Turns raw agent events into plain-English activity lines and map choreography cues. */
import type { AgentName, AnalysisEvent } from "./api-types";
import { fmtDistance } from "./format";
import { placeMeta } from "./places";

type Args = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN);

const TOOL_TEXT: Record<string, (a: Args) => string> = {
  get_building_overview: () => "Reading the building's footprint and height",
  check_size_fit: () => "Checking whether the space fits your size needs",
  inspect_roof: (a) =>
    a.focus === "equipment" ? "Scanning the roof for HVAC units" : a.focus === "defects" ? "Looking for roof defects" : "Scanning the roof condition",
  inspect_site_paving: () => "Measuring paved area for parking",
  compare_with_neighbors: (a) => `Comparing ${String(a.attribute ?? "this building").replace(/_/g, " ")} with neighbors`,
  get_imagery_metadata: () => "Checking how recent the aerial imagery is",
  lookup_vexcel_field: (a) => `Digging into ${String(a.field ?? "Vexcel fields")}`,
  count_places: (a) => `Counting ${placeMeta(String(a.group ?? "")).label.toLowerCase()} within ${fmtDistance(num(a.radius_m))}`,
  get_building_mix: (a) => `Surveying building types within ${fmtDistance(num(a.radius_m))}`,
  get_access_options: (a) => `Finding transit & parking within ${fmtDistance(num(a.radius_m ?? 400))}`,
  get_demographics: () => "Looking up census demographics",
  identify_jurisdiction: () => "Identifying which city rules apply",
  check_permitted_use: () => "Checking whether your use is permitted",
  compute_parking_requirement: () => "Computing required parking",
  list_use_requirements: () => "Listing the permits you'll need",
  check_accessibility_signals: () => "Checking accessibility signals",
  get_rent_assumption: () => "Looking up local rent levels",
  list_cost_items: () => "Reviewing possible conversion costs",
  estimate_costs: () => "Estimating upfront & monthly costs",
};

export function toolText(tool: string, args: Args = {}): string {
  return TOOL_TEXT[tool]?.(args) ?? tool.replace(/_/g, " ");
}

/** One short line describing an event, for the mission-control rows. */
export function eventText(e: AnalysisEvent): string {
  const data = (e.data ?? {}) as Args;
  switch (e.type) {
    case "tool_call":
      return toolText(String(data.tool ?? ""), (data.args as Args) ?? {});
    case "start":
      return "Getting started";
    case "done":
      return "Finished";
    case "skipped":
      return e.message.replace(/^Skipped:\s*/i, "Skipped — ");
    case "error":
      return "Ran into a problem";
    case "followup":
      return e.message.startsWith("Follow-up") ? "Following up on a question that could change the verdict" : e.message;
    case "validation":
      return "Validating evidence and rules";
    case "plan":
      return e.message.startsWith("Phase") ? e.message.split(":")[0] : "Planning the investigation";
    case "thinking":
      return "Thinking it through";
    default:
      return e.message;
  }
}

/** Compliance checklist chips that tick in as the Compliance Agent works. */
export const COMPLIANCE_CHIPS: Record<string, string> = {
  identify_jurisdiction: "Jurisdiction",
  check_permitted_use: "Permitted use",
  compute_parking_requirement: "Parking",
  list_use_requirements: "Permits",
  check_accessibility_signals: "Accessibility",
};

export const AGENT_ORDER: AgentName[] = ["vexcel", "neighborhood", "compliance", "cost", "matterport"];

export type AgentState = "waiting" | "running" | "done" | "error" | "skipped";

export function agentState(events: AnalysisEvent[], finished: boolean): AgentState {
  if (events.length === 0) return finished ? "skipped" : "waiting";
  let last = -1;
  events.forEach((e, i) => {
    if (e.type === "done" || e.type === "error" || e.type === "skipped") last = i;
  });
  const reopened = events.slice(last + 1).some((e) => e.type === "start" || e.type === "tool_call");
  if (last >= 0 && !reopened) return events[last].type === "done" ? "done" : events[last].type === "error" ? "error" : "skipped";
  return finished ? "done" : "running";
}

/** "E22: Upfront $189,433–492,333; monthly …" -> upfront high/low numbers (for the $ ticker). */
export function parseUpfront(message: string): { low: number; high: number } | null {
  const m = message.match(/Upfront \$([\d,]+)[–-]\$?([\d,]+)/);
  if (!m) return null;
  return { low: Number(m[1].replace(/,/g, "")), high: Number(m[2].replace(/,/g, "")) };
}

export const fmtClock = (s: number | null | undefined) => {
  if (s == null || !Number.isFinite(s)) return "—";
  const v = Math.max(0, Math.round(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
};
