import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";

/** Skips a request for the first pixel of a drag that is about to travel two
 * hundred more; {@link usePreview}'s one-at-a-time rule protects the server. */
export const PREVIEW_DEBOUNCE_MS = 80;

type PreviewBody = Parameters<typeof renderPreview>[1];

function identityOf(templateName: string, key: string | null, design: string): string {
  return JSON.stringify([templateName, key, design]);
}

function replacingUrl(next: string | null) {
  return (previous: string | null) => {
    if (previous) URL.revokeObjectURL(previous);
    return next;
  };
}

interface Job {
  templateName: string;
  key: string;
  design: string;
  identity: string;
}

/**
 * The editors' debounced preview loop, one request in flight at a time
 * (docs/architecture.md, *Two sizes, one pipeline*). It renders at `editor`
 * scale, so the image that comes back must not be measured for the coordinate
 * space: see `QuadEditor`'s `space` prop.
 */
export function usePreview(
  templateName: string,
  body: PreviewBody | null,
  design: string,
  strict = false,
  onPending?: (pending: boolean) => void,
): string | null {
  const pendingListener = useRef(onPending);
  const [displayedTemplate, setDisplayedTemplate] = useState(templateName);
  const latest = useRef("");
  const key = body === null ? null : JSON.stringify(body);
  const requestIdentity = identityOf(templateName, key, design);
  const strictMode = useRef(strict);
  useLayoutEffect(() => {
    latest.current = requestIdentity;
    strictMode.current = strict;
    pendingListener.current = onPending;
  }, [requestIdentity, strict, onPending]);
  const [url, setUrl] = useState<string | null>(null);

  // A ref, so the unmount revoke below never re-runs per URL.
  const current = useRef<string | null>(null);
  useEffect(() => {
    current.current = url;
  }, [url]);

  const queued = useRef<Job | null>(null);
  const busy = useRef(false);
  const generation = useRef(0);

  const pump = useCallback(async () => {
    async function renderJob(job: Job) {
      const sent = generation.current;
      try {
        const next = await renderPreview(
          job.templateName,
          JSON.parse(job.key) as PreviewBody,
          job.design,
          "editor",
        );
        const current = sent === generation.current;
        const stale = !current || (strictMode.current && latest.current !== job.identity);
        if (stale) {
          URL.revokeObjectURL(next);
          return;
        }
        setDisplayedTemplate(job.templateName);
        setUrl(replacingUrl(next));
        pendingListener.current?.(false);
      } catch {
        const current = sent === generation.current;
        if (current && latest.current === job.identity) pendingListener.current?.(false);
        if (strictMode.current && current) setUrl(replacingUrl(null));
      }
    }

    if (busy.current) return;
    busy.current = true;
    try {
      while (queued.current) {
        const job = queued.current;
        queued.current = null;
        await renderJob(job);
      }
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    // The next template's render may install its listener before this cleanup runs.
    const notify = pendingListener.current;
    return () => {
      generation.current += 1;
      queued.current = null;
      notify?.(false);
    };
  }, [templateName]);

  useEffect(
    () => () => {
      generation.current += 1;
      if (current.current) URL.revokeObjectURL(current.current);
    },
    [],
  );

  useEffect(() => {
    if (key === null) {
      pendingListener.current?.(false);
      return;
    }
    pendingListener.current?.(true);
    const timer = setTimeout(() => {
      queued.current = {
        templateName,
        key,
        design,
        identity: identityOf(templateName, key, design),
      };
      void pump();
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [templateName, key, design, pump]);

  return strict && displayedTemplate !== templateName ? null : url;
}
