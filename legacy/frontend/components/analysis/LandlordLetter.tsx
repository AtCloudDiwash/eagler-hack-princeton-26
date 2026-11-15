"use client";

import { CheckIcon, ClipboardDocumentIcon } from "@heroicons/react/20/solid";
import { useState } from "react";
import { Button } from "../ui/Button";

type CopyState = "idle" | "copied" | "failed";

/** Drafted landlord request (plain text with newlines) with a copy-to-clipboard button. */
export function LandlordLetter({ letter }: { letter: string }) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const text = letter?.trim() ?? "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
    setTimeout(() => setCopyState("idle"), 2000);
  }

  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Draft letter to landlord</p>
        {text && (
          <Button variant="secondary" size="sm" onClick={copy} aria-live="polite">
            {copyState === "copied" ? (
              <CheckIcon className="size-4 text-pass" aria-hidden />
            ) : (
              <ClipboardDocumentIcon className="size-4" aria-hidden />
            )}
            {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy"}
          </Button>
        )}
      </div>
      <pre
        data-testid="landlord-letter"
        className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-navy-900 p-3 font-mono text-xs leading-relaxed text-ink"
      >
        {text || "N/A"}
      </pre>
    </div>
  );
}
