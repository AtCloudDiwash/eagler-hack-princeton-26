"use client";

// Tiny data-loading hook for client components: loading / error / success, abort on change,
// and a retry() for error states. State is keyed by request so a new key reads as "loading"
// immediately without a synchronous setState inside the effect.

import { useCallback, useEffect, useEffectEvent, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: undefined; error: undefined }
  | { status: "error"; data: undefined; error: unknown }
  | { status: "success"; data: T; error: undefined };

type Settled<T> = { requestId: string } & AsyncState<T>;

export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string,
): AsyncState<T> & { retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const requestId = `${key}#${attempt}`;
  const runLoad = useEffectEvent(load);

  useEffect(() => {
    const controller = new AbortController();
    runLoad(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ requestId, status: "success", data, error: undefined });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setSettled({ requestId, status: "error", data: undefined, error });
      },
    );
    return () => controller.abort();
  }, [requestId]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  if (!settled || settled.requestId !== requestId) {
    return { status: "loading", data: undefined, error: undefined, retry };
  }
  if (settled.status === "success") return { status: "success", data: settled.data, error: undefined, retry };
  return { status: "error", data: undefined, error: settled.error, retry };
}
