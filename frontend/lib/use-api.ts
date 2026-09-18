"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> = {
  data: T | null;
  error: string;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (value: T | null) => void;
};

/**
 * Tiny data-fetching hook: runs `fn` on mount (and whenever `deps` change),
 * exposes loading/error state and a manual `reload`.
 *
 * The API client already retries cold starts and publishes progress through
 * `useServerState`, so this hook only has to track the request itself.
 */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fnRef.current());
      setError("");
    } catch (e) {
      setError((e as Error).message || "Request failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload: run, setData };
}
