import { useEffect, useState } from "react";

import { getJson } from "./client";

export interface Resource<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

/**
 * Load a JSON resource by its URL; `null` loads nothing. When the URL changes, the
 * previous request is cancelled and its late answer ignored, so a slow response for
 * an earlier choice can never overwrite the current one.
 */
export function useResource<T>(path: string | null): Resource<T> {
  const [state, setState] = useState<{ path: string; data?: T; error?: string } | null>(null);

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    getJson<T>(path, controller.signal).then(
      (data) => setState({ path, data }),
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ path, error: error instanceof Error ? error.message : String(error) });
        }
      },
    );
    return () => controller.abort();
  }, [path]);

  if (path === null) return { loading: false };
  // State from an earlier URL means this one is still loading.
  if (state?.path !== path) return { loading: true };
  return { data: state.data, error: state.error, loading: false };
}
