import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSettings,
  saveSettings,
  type SettingsChanges,
  type WorkspaceSettings,
} from "../../api/workspaceSettings";
import type { SaveStatus } from "./useShopSettings";

/** One revision and save queue for settings.yaml, independent of Shop.
 * Responses advance the revision without replacing newer local edits.
 * A conflict stops queued edits until an explicit reload (ADR-0055).
 */
export function useWorkspaceSettings() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [loadedVersion, setLoadedVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const revision = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const waiting = useRef(0);
  const conflicted = useRef(false);
  const failed = useRef<SettingsChanges>({});

  const adopt = useCallback((loaded: WorkspaceSettings) => {
    revision.current = loaded.revision;
    conflicted.current = false;
    failed.current = {};
    setSettings(loaded);
    setLoadedVersion((version) => version + 1);
    setLoadError(null);
    setFieldErrors({});
    setStatus({ kind: "idle" });
  }, []);
  const refuse = useCallback((error: unknown) => {
    setSettings(null);
    setLoadError(error instanceof Error ? error.message : "Could not read settings.yaml");
  }, []);
  const reload = useCallback(
    () => queue.current.then(() => getSettings()).then(adopt, refuse),
    [adopt, refuse],
  );
  useEffect(() => {
    let active = true;
    getSettings().then(
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
  }, [adopt, refuse]);

  const save = useCallback((changes: SettingsChanges) => {
    if (conflicted.current) return;
    waiting.current += 1;
    setStatus({ kind: "saving" });
    const run = async () => {
      try {
        if (conflicted.current || revision.current === null) return;
        const outcome = await saveSettings(revision.current, changes);
        if (outcome.kind === "saved") {
          revision.current = outcome.settings.revision;
          failed.current = Object.fromEntries(
            Object.entries(failed.current).filter(([field]) => !(field in changes)),
          );
          setFieldErrors((errors) =>
            Object.fromEntries(
              Object.entries(errors).filter(
                ([key]) =>
                  !(key.startsWith("batch_ai") && "concurrency" in changes) &&
                  !(key.startsWith("ai.providers") && "providers" in changes) &&
                  !(key === "ai.step_limit_minutes" && "step_limit_minutes" in changes) &&
                  !(key === "ai.run_limit_minutes" && "run_limit_minutes" in changes) &&
                  !(key.startsWith("market_seo") && "weights" in changes),
              ),
            ),
          );
          if (waiting.current === 1)
            setStatus(
              Object.keys(failed.current).length
                ? { kind: "error", message: "Not saved" }
                : { kind: "saved" },
            );
        } else if (outcome.kind === "conflict") {
          conflicted.current = true;
          setStatus({ kind: "conflict", message: outcome.message });
        } else {
          failed.current = { ...failed.current, ...changes };
          setFieldErrors((errors) => ({ ...errors, ...outcome.fieldErrors }));
          setStatus({ kind: "error", message: "Not saved" });
        }
      } catch (error) {
        failed.current = { ...failed.current, ...changes };
        setStatus({
          kind: "error",
          message: error instanceof Error ? error.message : "Could not save settings.yaml",
        });
      } finally {
        waiting.current -= 1;
      }
    };
    queue.current = queue.current.then(run, run);
  }, []);

  return {
    settings,
    loadedVersion,
    status,
    fieldErrors,
    loadError,
    reload,
    save,
    retry: () => save({ ...failed.current }),
    locked: status.kind === "conflict",
  };
}
