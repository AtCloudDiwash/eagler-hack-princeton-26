import type { Metadata } from "next";
import { Suspense } from "react";
import { LoadingBlock } from "@/components/ui/Spinner";
import { PropertiesView } from "./PropertiesView";

export const metadata: Metadata = { title: "Candidate spaces · Turnkey Matchmaker" };

// The view reads the query string with useSearchParams, so it renders on the client inside a
// Suspense boundary; the shell (header, footer, fallback) is prerendered.
export default function PropertiesPage() {
  return (
    <Suspense fallback={<LoadingBlock message="Loading search…" />}>
      <PropertiesView />
    </Suspense>
  );
}
