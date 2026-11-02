import { useCallback, useEffect, useState } from "react";

/**
 * One revisioned file's loading, shared by `shop.yaml` and `settings.yaml`.
 * It loads once on mount; `reload` waits for queued saves first. A load
 * resets the save queue to the file's revision and bumps `loadedVersion`,
 * the signal for controls to drop local drafts.
 *
 * `onLoaded` and `onRefused` must be stable (a state setter, or a
 * `useCallback`).
 */
export function useQueuedFile<T extends { revision: string }>({
  load,
  queue,
  onLoaded,
  onRefused,
  fallback,
}: {
  load: () => Promise<T>;
  queue: {
    reset: (revision: string) => void;
    afterSaves: <R>(next: () => Promise<R>) => Promise<R>;
  };
  onLoaded: (loaded: T) => void;
  onRefused?: () => void;
  fallback: string;
}) {
  const [loadedVersion, setLoadedVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { reset, afterSaves } = queue;

  const adopt = useCallback(
    (loaded: T) => {
      reset(loaded.revision);
      onLoaded(loaded);
      setLoadedVersion((version) => version + 1);
      setLoadError(null);
    },
    [reset, onLoaded],
  );
  const refuse = useCallback(
    (error: unknown) => {
      onRefused?.();
      setLoadError(error instanceof Error ? error.message : fallback);
    },
    [onRefused, fallback],
  );
  const reload = useCallback(
    () => afterSaves(load).then(adopt, refuse),
    [afterSaves, load, adopt, refuse],
  );

  useEffect(() => {
    let active = true;
    load().then(
      (loaded) => {
        if (active) adopt(loaded);
      },
      (error: unknown) => {
        if (active) refuse(error);
      },
    );
    return () => {
      active = false;
    };
  }, [load, adopt, refuse]);

  return { loadedVersion, loadError, reload };
}
