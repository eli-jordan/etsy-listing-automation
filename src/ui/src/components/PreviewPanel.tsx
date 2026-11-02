import { useCallback, useEffect, useRef, useState } from "react";
import { renderPreview } from "../api/calibrator";
import { Lightbox } from "./Lightbox";
import { previewProgress, type PreviewResult } from "./previewProgress";

/**
 * The Preview tab, for every template kind.
 *
 * The split it completes: the Calibrate tab renders *small* so that dragging
 * is instant, and this one renders at the photo's real size so there is
 * somewhere to actually judge the result. Both go through the same server-side
 * pipeline `apply` uses -- what changes between them is only how many pixels
 * the server is asked to spend.
 *
 * **Opening the tab renders; changing a box does not.** A full-size render of
 * a twelve-colour set is a lot of work, and it used to be kicked off by any
 * change to the config at all -- so nudging a box by a pixel re-rendered the
 * lot. Worse, the tiles could quietly become a picture of an older box than
 * the one on screen, which is the one thing a view you approve from must never
 * do. So the first look renders, and after that a changed config turns
 * Re-render red rather than silently re-running.
 *
 * The panel stays mounted while the Calibrate tab is in front, hidden rather
 * than unmounted. Otherwise every flick between tabs would throw the renders
 * away and start the set again -- and "there is none, so render" would fire on
 * a set that had just been rendered.
 *
 * Renders **sequentially**. Firing every colour at once does not make the set
 * arrive sooner -- the server runs the real pipeline for each -- it only makes
 * the *first* one arrive later, and buries the progress count.
 */

type PreviewBody = Parameters<typeof renderPreview>[1];

export interface PreviewJob {
  /** Stable across renders; also the lightbox's key. A colour name for a
   * colour matrix, the template name for the kinds with one output. */
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
  /** Whether this tab is the one in front. Mounted either way -- see the note
   * about tab flicks above -- so this both hides the panel and is what a first
   * look keys off. */
  active: boolean;
  /** Colour-matrix's "Approve & mark calibrated", which is a save. Omitted by
   * the kinds whose only save is the header's -- there is nothing extra to
   * approve when the tab shows one image. */
  onApprove?: () => void;
}

/** What one press of Render asked for. Set once and never mutated, so the
 * render loop's dependency on it is honest: a later edit produces a *new*
 * request, it does not redirect the one in flight. */
interface Request {
  key: string;
  templateName: string;
  design: string;
  jobs: PreviewJob[];
}

function requestKey(templateName: string, design: string, jobs: PreviewJob[]): string {
  return `${templateName}|${design}|${JSON.stringify(jobs)}`;
}

/** A tile rendered for the run `key` names; a late answer for an older run
 * changes nothing. */
function withRendered(current: PreviewResult | null, key: string, id: string, url: string) {
  if (current === null || current.key !== key) return current;
  return { ...current, rendered: { ...current.rendered, [id]: url }, done: current.done + 1 };
}

function withFailure(current: PreviewResult | null, key: string) {
  if (current === null || current.key !== key) return current;
  return { ...current, failed: current.failed + 1 };
}

/** Renders a request's jobs one at a time, reporting each outcome. The
 * returned function cancels: nothing is reported after it, and a render that
 * lands afterwards is revoked rather than handed over. */
function runRequest(
  request: Request,
  report: { onRendered: (id: string, url: string) => void; onFailed: () => void },
): () => void {
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
        // One unreadable photo costs you that tile, not the whole tab.
        if (cancelled) return;
        report.onFailed();
      }
    }
  })();

  return () => {
    cancelled = true;
  };
}

/** How far the run is (`asked` jobs), or how many colours there are to
 * render before the first one. */
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

/** Why nothing can render yet, with the way out when there is one. */
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

/** Render's emphasis: danger when stale, quiet once approval is the next step. */
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

  // Every blob this panel has made. Revoked wholesale when a run is replaced
  // or the tab goes away -- never per tile, which would pull an image out from
  // under one still on screen.
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

  // The first look renders itself. Only ever the *first*: once a request
  // exists this is inert, so returning to the tab shows what was rendered
  // rather than spending the set again.
  //
  // Adjusted during render rather than from an effect. React re-renders
  // immediately and throws the intermediate output away, so the panel never
  // paints a "nothing yet" state it is about to replace -- where an effect
  // would both paint it and cost the cascading render that
  // `react-hooks/set-state-in-effect` exists to prevent. Nothing to revoke
  // here either: `request` only ever goes from null to set, so there cannot
  // be an earlier run's blobs to clean up. That is why this is not `start()`.
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
        {/* Which button is the loud one follows what there is to do. A config
            that has moved on since the render makes Re-render *red*: that is
            the one state where what you are looking at is not what you would
            be approving, and it is worth more than a line of prose beside the
            progress count, which is what it replaced. `.btn` alone is
            transparent in this design system, so the quiet one is explicitly
            `btn-secondary` rather than bare. */}
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
          Full-size renders, through the same pipeline <code>apply</code> uses — a few seconds each,
          which is why they are asked for rather than assumed. Click one to see it large.
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
          <p className="mg-help">Full-size renders. Click an image to see it large.</p>
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
