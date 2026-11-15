// Typed access to the JSON fixture (JSON imports widen literals like "PASS" to string).
import type { AnalyzeResponse } from "@/lib/types";
import raw from "./analysis.json";

export const analysisFixture = raw as unknown as AnalyzeResponse;
