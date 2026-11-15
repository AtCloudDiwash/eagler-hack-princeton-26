import type { Metadata } from "next";
import { Suspense } from "react";
import { LoadingBlock } from "@/components/ui/Spinner";
import { AnalysisView } from "./AnalysisView";

export const metadata: Metadata = { title: "Analysis report · Turnkey Matchmaker" };

// Analysis ids are only known at request time, so the client view (useParams) sits inside a
// Suspense boundary as Cache Components requires; the stored report is fetched in the browser.
export default function AnalysisPage() {
  return (
    <Suspense fallback={<LoadingBlock message="Loading analysis…" />}>
      <AnalysisView />
    </Suspense>
  );
}
