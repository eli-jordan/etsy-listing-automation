import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { FileZipIcon } from "@phosphor-icons/react/dist/csr/FileZip";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { stageDesigns, StagingRefused, type StagingRefusal } from "../api/batches";
import { listListingTemplates } from "../api/listingTemplates";
import { ownedTile } from "../media";
import type { ListingTemplateSummary } from "../types";

/**
 * New batch (UI doc §4; the `new-batch` and `staging-refused` frames): pick
 * one listing template, then drop designs. A drop is posted straight to
 * staging and lands on the staging review; a refused one stays here with the
 * reason and the remedy, and nothing was kept. `?template=` preselects, as
 * Start batch on a card does.
 *
 * Loose PNGs only in this slice (batch plan PR 2): a ZIP is refused by the
 * server as coming soon until PR 7.
 *
 * A drop on a listing-template card that the server refuses lands here too,
 * the refusal in the navigation's state (UI doc §2, closed question 2), so
 * a card has no refusal state of its own.
 */

/** A refusal, and the names of the files it was about. Names rather than
 * the files: it may arrive in history state from a card drop. */
export interface Refused extends StagingRefusal {
  files: string[];
}

function refusedHeading(files: string[]): string {
  const [only] = files;
  return files.length === 1 && only ? `${only} was not staged.` : "These files were not staged.";
}

export function NewBatchPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const handed = (useLocation().state as { refused?: Refused } | null)?.refused ?? null;
  const [templates, setTemplates] = useState<ListingTemplateSummary[] | null>(null);
  const [chosen, setChosen] = useState(params.get("template") ?? "");
  const [refused, setRefused] = useState<Refused | null>(handed);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let current = true;
    listListingTemplates()
      .then((loaded) => {
        if (!current) return;
        setTemplates(loaded);
        setChosen((name) => (loaded.some((t) => t.name === name) ? name : (loaded[0]?.name ?? "")));
      })
      .catch(() => current && setError("Could not load listing templates"));
    return () => {
      current = false;
    };
  }, []);

  function stage(files: File[]) {
    if (files.length === 0 || !chosen || busy) return;
    setBusy(true);
    setError("");
    stageDesigns(chosen, files)
      .then((session) => navigate(`/batches/staging/${session.id}`))
      .catch((exc: unknown) => {
        setBusy(false);
        if (exc instanceof StagingRefused) {
          setRefused({ ...exc.refusal, files: files.map((file) => file.name) });
        } else setError(exc instanceof Error ? exc.message : "The designs could not be staged.");
      });
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    stage(Array.from(event.dataTransfer.files));
  }

  const template = templates?.find((t) => t.name === chosen);
  const minimum = template?.design_minimum;

  return (
    <>
      <div className="page-head">
        <Link className="page-head__crumb" to="/listing-templates">
          Listing templates
        </Link>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">New batch</h1>
      </div>

      {error && (
        <p className="app__status" role="alert">
          {error}
        </p>
      )}

      <div className="bc-steps">
        <section className="bc-step">
          <h2>1. Listing template</h2>
          <p className="bc-muted bc-small">
            Every design in this batch gets the same product settings.
          </p>
          <div className="bc-picks" role="radiogroup" aria-label="Listing template">
            {(templates ?? []).map((t) => (
              <button
                key={t.name}
                type="button"
                role="radio"
                aria-checked={t.name === chosen}
                className={t.name === chosen ? "bc-pick bc-pick--on" : "bc-pick"}
                onClick={() => setChosen(t.name)}
              >
                {t.media[0] !== undefined && (
                  <img
                    src={ownedTile(t.media[0], { kind: "listing-template", name: t.name })}
                    alt=""
                  />
                )}
                <span className="bc-cell__text">
                  <span className="bc-pick__name">{t.name}</span>
                  <span className="bc-pick__facts">
                    {t.garment} · {t.colour_count} colours
                  </span>
                </span>
              </button>
            ))}
          </div>
          {templates !== null && templates.length === 0 && (
            <p className="bc-small bc-muted">
              There are no listing templates yet. Open a finished listing and choose Save as listing
              template.
            </p>
          )}
        </section>

        <section className="bc-step">
          <h2>2. Designs</h2>
          <p className="bc-muted bc-small">
            One ZIP, or any number of loose PNGs. Up to 25 designs per batch.
          </p>

          {refused && (
            <div
              className="dv-callout dv-callout--blocked"
              style={{ marginBottom: "var(--space-3)" }}
              role="alert"
            >
              <WarningCircleIcon className="dv-callout__icon" />
              <div>
                <strong>{refusedHeading(refused.files)}</strong>
                <div>{refused.message}</div>
                <div className="dv-callout__remedy">{refused.remedy}</div>
              </div>
            </div>
          )}

          <div
            className={refused ? "bc-drop bc-drop--error" : "bc-drop"}
            role="button"
            tabIndex={0}
            aria-disabled={!chosen || busy}
            onClick={() => input.current?.click()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") input.current?.click();
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={onDrop}
          >
            <FileZipIcon className="bc-drop__icon" />
            <span className="bc-drop__title">
              {busy
                ? "Staging…"
                : refused
                  ? "Drop a different ZIP or PNGs"
                  : "Drop a ZIP or PNGs here"}
            </span>
            <span className="bc-small bc-muted">
              Kittl exports work as they are. Every PNG in the ZIP, in any folder, becomes a design.
            </span>
            <span className="bc-row" style={{ marginTop: "var(--space-1)" }}>
              <button type="button" className="btn btn-secondary" disabled={!chosen || busy}>
                Choose files…
              </button>
            </span>
            <input
              ref={input}
              type="file"
              accept=".png,.zip,image/png,application/zip"
              multiple
              hidden
              aria-label="Design files"
              onChange={(event) => {
                stage(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
          </div>

          <div className="bc-reqs">
            <span className="bc-req">
              <CheckCircleIcon className="bc-icon" />
              PNG with a transparent background
            </span>
            {minimum && template && (
              <span className="bc-req">
                <CheckCircleIcon className="bc-icon" />
                At least {minimum.width} × {minimum.height} px (90% of the {template.garment} print
                area)
              </span>
            )}
            <span className="bc-req">
              <CheckCircleIcon className="bc-icon" />
              Not both a ZIP and loose PNGs, and never more than one ZIP
            </span>
          </div>
        </section>
      </div>
    </>
  );
}
