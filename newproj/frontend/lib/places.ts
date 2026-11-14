/** Place groups (mirrors backend/config/place_groups.yaml) so map dots, legends and agent activity agree. */
import { colorFor } from "./format";

export const PLACE_GROUPS: Record<string, { label: string; color: string }> = {
  food_drink: { label: "Restaurants & cafes", color: "#f97316" },
  dental_medical: { label: "Dental & medical", color: "#f43f5e" },
  fitness: { label: "Gyms & fitness", color: "#a855f7" },
  transit: { label: "Transit stops", color: "#38bdf8" },
  parking: { label: "Public parking", color: "#94a3b8" },
  offices: { label: "Offices", color: "#22d3ee" },
  lodging: { label: "Hotels & attractions", color: "#eab308" },
  education: { label: "Schools & universities", color: "#84cc16" },
  entertainment: { label: "Entertainment & venues", color: "#ec4899" },
  retail: { label: "Shops", color: "#14b8a6" },
  residential_services: { label: "Community & daily needs", color: "#64748b" },
};

export const placeMeta = (group: string) => PLACE_GROUPS[group] ?? { label: group.replace(/_/g, " "), color: colorFor(group) };

/** Neighborhood.place_groups is keyed by label; map a label back to its group id. */
export const groupIdForLabel = (label: string) => Object.entries(PLACE_GROUPS).find(([, m]) => m.label === label)?.[0] ?? label;
