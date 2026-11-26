import { useCallback, useEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";
import { useIsPhone } from "../phone/usePhone";
import { Lightbox } from "./Lightbox";
import { previewProgress, type PreviewResult } from "./previewProgress";

type PreviewBody = Parameters<typeof renderPreview>[1];

export interface PreviewJob {
  /** The colour for a colour matrix, else the template name; the lightbox keys on it. */
  id: string;
  label: string;
  body: PreviewBody;
}

interface Props {
  fullQuality?: boolean;
  reference?: string;
  blocked?: string | null;
  prepareLabel?: string;
  onPrepare?: () => void;
  identity?: string;
  templateName: string;
  jobs: PreviewJob[];
  design: string;
  active: boolean;
  onApprove?: () => void;
}

/** What one press of Render asked for; a later edit makes a new one. */
type Request = Readonly<{
  key: string;
  templateName: string;
  design: string;
  jobs: readonly PreviewJob[];
}>;

function requestKey(templateName: string, design: string, jobs: PreviewJob[]): string {
  return `${templateName}|${design}|${JSON.stringify(jobs)}`;
}

function withRendered(current: PreviewResult | null, key: string, id: string, url: string) {
  if (current === null || current.key !== key) return current;
  return { ...current, rendered: { ...current.rendered, [id]: url }, done: current.done + 1 };
}

function withFailure(current: PreviewResult | null, key: string) {
  if (current === null || current.key !== key) return current;
  return { ...current, failed: current.failed + 1 };
}

type Cancel = () => void;

function runRequest(
  request: Request,
  report: { onRendered: (id: string, url: string) => void; onFailed: () => void },
): Cancel {
  let cancelled = false;

  void (async () => {
    for (const job of request.jobs) {
      if (cancelled) return;
      try {
        const url = await renderPreview(request.templateName, job.body, request.design, "full");
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        report.onRendered(job.id, url);
      } catch {
        if (cancelled) return;
        report.onFailed();
      }
    }
  })();

  return () => {
    cancelled = true;
  };
}

function ProgressCount({
  asked,
  colours,
  done,
}: {
  asked: number | null;
  colours: number;
  done: number;
}) {
  if (asked !== null) return <span className="preview-grid__count">{`${done} / ${asked}`}</span>;
  return (
    <span className="preview-grid__status">
      {colours === 1 ? "not rendered yet" : `${colours} colours, not rendered yet`}
    </span>
  );
}

function BlockedNotice({
  blocked,
  prepareLabel,
  onPrepare,
}: {
  blocked: string;
  prepareLabel: string;
  onPrepare: (() => void) | undefined;
}) {
  return (
    <div className="mg-empty-preview">
      <p role="status">{blocked}</p>
      {onPrepare && (
        <button type="button" className="btn btn-primary" onClick={onPrepare}>
          {prepareLabel}
        </button>
      )}
    </div>
  );
}

function PreviewTile({
  label,
  url,
  onOpen,
}: {
  label: string;
  url: string | undefined;
  onOpen: () => void;
}) {
  return (
    <figure className="gallery__item preview-grid__tile">
      {url ? (
        <button
          type="button"
          className="preview-grid__open"
          onClick={onOpen}
          title="Open at full size"
        >
          <img src={url} alt={label} />
        </button>
      ) : (
        <div className="gallery__placeholder" />
      )}
      <figcaption>{label}</figcaption>
    </figure>
  );
}

/** `.btn` alone is transparent in this design system, so the quiet button is `btn-secondary`. */
function renderButtonClass(stale: boolean, approvable: boolean): string {
  if (stale) return "btn btn-danger";
  return approvable ? "btn btn-secondary" : "btn btn-primary";
}

export function PreviewPanel({
  fullQuality,
  reference,
  templateName,
  jobs,
  design,
  active,
  onApprove,
  blocked = null,
  prepareLabel = "Prepare template",
  onPrepare,
  identity = "",
}: Props) {
  const key = requestKey(templateName, design, jobs) + identity;
  const [request, setRequest] = useState<Request | null>(null);
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [actualSize, setActualSize] = useState(false);
  const urlsRef = useRef<string[]>([]);
  const verb = useIsPhone() ? "Tap" : "Click";

  // Never per tile: that would pull an image out from under one still on screen.
  const revokeAll = useCallback(() => {
    for (const url of urlsRef.current) URL.revokeObjectURL(url);
    urlsRef.current = [];
  }, []);
  useEffect(() => revokeAll, [revokeAll]);

  const start = useCallback(() => {
    revokeAll();
    setOpen(null);
    setResult({ key, rendered: {}, done: 0, failed: 0 });
    setRequest({ key, templateName, design, jobs });
  }, [key, templateName, design, jobs, revokeAll]);

  // Adjusted during render, not in an effect, so the panel never paints the
  // empty state it is about to replace. `request` only goes from null to set,
  // so there are no earlier blobs to revoke.
  if (active && request === null && !blocked) {
    setRequest({ key, templateName, design, jobs });
    setResult({ key, rendered: {}, done: 0, failed: 0 });
  }

  useEffect(() => {
    if (request === null || request.key !== key || blocked) return;
    return runRequest(request, {
      onRendered: (id, url) => {
        urlsRef.current.push(url);
        setResult((current) => withRendered(current, request.key, id, url));
      },
      onFailed: () => setResult((current) => withFailure(current, request.key)),
    });
  }, [request, key, blocked]);

  const { rendered, done, failed, stale, complete, approvable } = previewProgress(
    request,
    result,
    key,
  );

  const items = (request?.jobs ?? [])
    .map((job) => ({ id: job.id, label: job.label, url: rendered[job.id] }))
    .filter((item): item is { id: string; label: string; url: string } => Boolean(item.url));
  const openIndex = open === null ? -1 : items.findIndex((item) => item.id === open);

  return (
    <section
      className={jobs.length === 1 ? "preview-grid preview-grid--single" : "preview-grid"}
      hidden={!active}
    >
      {blocked && (
        <BlockedNotice blocked={blocked} prepareLabel={prepareLabel} onPrepare={onPrepare} />
      )}
      <div className="preview-grid__head">
        <ProgressCount asked={request?.jobs.length ?? null} colours={jobs.length} done={done} />
        {request !== null && !complete && !stale && !blocked && (
          <span className="preview-grid__status">rendering at full size…</span>
        )}
        {fullQuality && complete && <span className="preview-grid__status">Full quality</span>}
        {failed > 0 && (
          <span className="preview-grid__failed">
            {`${failed} ${failed === 1 ? "preview" : "previews"} failed to render`}
          </span>
        )}
        <div className="preview-grid__actions">
          <button
            type="button"
            className={renderButtonClass(stale, approvable)}
            disabled={!!blocked}
            onClick={start}
          >
            {request === null ? "Render preview" : "Re-render"}
          </button>
          {onApprove && (
            <button
              type="button"
              className={approvable ? "btn btn-primary" : "btn btn-secondary"}
              onClick={onApprove}
            >
              Approve &amp; mark calibrated
            </button>
          )}
        </div>
      </div>

      {request === null ? (
        <p className="preview-grid__empty">
          Full-size renders, through the same pipeline <code>apply</code>
          {` uses — a few seconds each, which is why they are asked for rather than assumed. ${verb} one to see it large.`}
        </p>
      ) : (
        <div className="preview-grid__tiles">
          {request.jobs.map((job) => (
            <PreviewTile
              key={job.id}
              label={job.label}
              url={rendered[job.id]}
              onOpen={() => setOpen(job.id)}
            />
          ))}
        </div>
      )}

      {fullQuality && request !== null && (
        <>
          <p className="mg-help">{`Full-size renders. ${verb} an image to see it large.`}</p>
          {reference && <p className="mg-help">{reference}</p>}
        </>
      )}

      {openIndex >= 0 && (
        <Lightbox
          items={items}
          index={openIndex}
          actualSize={actualSize}
          onActualSizeChange={setActualSize}
          onIndexChange={(next) => setOpen(items[next]?.id ?? null)}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  );
}
