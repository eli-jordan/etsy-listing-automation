import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  deleteListingTemplate,
  getListingTemplate,
  getListingTemplateDraft,
} from "../api/listingTemplates";
import { ActionLink } from "../components/ActionLink";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EditableName } from "../components/EditableName";
import { useAutosave } from "../hooks/useAutosave";
import { useUnsavedWarning } from "../hooks/useUnsavedWarning";
import type { MediaOwner } from "../media";
import type { ListingDetail, ListingTemplateDetail, ListingTemplateSource } from "../types";
import { EditorHead, ListingEditorShell } from "./ListingEditorPage";
import { HeadAlert } from "./editor/HeadAlert";
import { listingTemplateTransport, templateAsListing } from "./editor/listingTemplateDocument";
import { metaFor } from "./editor/saveMeta";
import { TEMPLATE_DELETE_DETAILS, templateDeleteTitle } from "./listingTemplateDelete";

const HOW_TO =
  "To make a listing template, open a finished listing and choose Create listing template.";

function sourceFrom(params: URLSearchParams): ListingTemplateSource | null {
  const listing = params.get("from_listing");
  if (listing) return { kind: "listing", name: listing };
  const template = params.get("from_template");
  if (template) return { kind: "listing-template", name: template };
  return null;
}

function ownerOf(template: ListingTemplateDetail): MediaOwner | null {
  if (template.name !== "") return { kind: "listing-template", name: template.name };
  if (template.source === null || template.source === undefined) return null;
  return {
    kind: template.source.kind,
    name: template.source.name,
    copies: Object.fromEntries(template.assets.map((asset) => [asset.ref, asset.source_ref])),
  };
}

interface Loaded {
  key: string;
  detail: ListingDetail;
  owner: MediaOwner | null;
}

export function ListingTemplateEditorPage() {
  const { name } = useParams<{ name?: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const routeName = name ?? null;
  const source = routeName === null ? sourceFrom(params) : null;
  const sourceKey = source === null ? null : `${source.kind}:${source.name}`;
  const key = routeName ?? sourceKey;

  // The template as the editor that just named it had it: naming crosses
  // from `/new` to `/:name`, a different route pattern, so this remounts.
  // `ListingEditorPage` hands its listing across for the same reason: no GET
  // that could answer older than the save the unmounting editor flushed.
  const handed =
    (useLocation().state as { listingTemplate?: ListingDetail } | null)?.listingTemplate ?? null;
  const [fetched, setFetched] = useState<Loaded | null>(null);
  const [loadError, setLoadError] = useState("");

  const matchingFetched = fetched !== null && fetched.key === key ? fetched : null;
  const initial: Loaded | null =
    handed !== null && handed.name === routeName
      ? {
          key: routeName,
          detail: handed,
          owner: { kind: "listing-template", name: routeName },
        }
      : matchingFetched;

  useEffect(() => {
    if (initial !== null || key === null) return;
    let current = true;
    const load =
      routeName !== null
        ? getListingTemplate(routeName)
        : getListingTemplateDraft(source as ListingTemplateSource);
    load
      .then((loaded) => {
        if (!current) return;
        setLoadError("");
        setFetched({ key, detail: templateAsListing(loaded), owner: ownerOf(loaded) });
      })
      .catch((error: unknown) => {
        if (current) setLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      current = false;
    };
    // `source` is rebuilt every render; `key` is what identifies it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, initial]);

  if (key === null) return <p className="app__status">{HOW_TO}</p>;
  if (loadError) return <p className="app__status">{loadError}</p>;
  if (initial === null) return <p className="app__status">Loading…</p>;

  return (
    <ListingTemplateEditor
      name={routeName}
      initial={initial}
      source={source}
      onBack={() => navigate("/listing-templates")}
      onNamed={(next, fresh) =>
        navigate(`/listing-templates/${encodeURIComponent(next)}`, {
          replace: true,
          state: { listingTemplate: fresh },
        })
      }
    />
  );
}

function ListingTemplateEditor({
  name,
  initial,
  source,
  onBack,
  onNamed,
}: {
  name: string | null;
  initial: Loaded;
  source: ListingTemplateSource | null;
  onBack: () => void;
  onNamed: (name: string, fresh: ListingDetail) => void;
}) {
  const [owner, setOwner] = useState(initial.owner);
  const { detail, update, flush, commitName, save } = useAutosave(name, initial.detail, {
    transport: listingTemplateTransport(source),
    onNamed: (next, fresh) => {
      setOwner({ kind: "listing-template", name: next });
      onNamed(next, fresh);
    },
  });

  const blocker = useUnsavedWarning(save.kind === "unsaved");
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState("");
  const savedName = detail.name || name;

  function clone(template: string) {
    void flush().then((settled) => {
      if (settled.written) {
        navigate(`/listing-templates/new?from_template=${encodeURIComponent(template)}`);
      }
    });
  }

  function confirmDelete(template: string) {
    setDeleting(false);
    setActionError("");
    deleteListingTemplate(template)
      // Replace, not push: Back must not return to a template that is gone,
      // and a replace is not held by the unsaved-edits warning -- the seller
      // has just confirmed they are done with it.
      .then(() => navigate("/listing-templates", { replace: true }))
      .catch(() => setActionError(`Could not delete ${template}`));
  }

  return (
    <>
      <ListingEditorShell
        kind="listing-template"
        detail={detail}
        update={update}
        flush={flush}
        owner={owner}
        head={
          <EditorHead
            kind="listing-template"
            detail={detail}
            onBack={onBack}
            flush={flush}
            title={
              <EditableName
                value={name ?? ""}
                onCommit={commitName}
                error={
                  save.kind === "name-taken"
                    ? { name: save.name, message: "that name is already taken" }
                    : null
                }
                busy={save.kind === "saving"}
                placeholder="Name this template…"
                label="Template name"
              />
            }
            meta={metaFor(save, detail.name || name, "listing-template")}
            actions={
              savedName && (
                <>
                  <ActionLink
                    icon={<CopySimpleIcon aria-hidden="true" />}
                    onClick={() => clone(savedName)}
                  >
                    Clone
                  </ActionLink>
                  <ActionLink
                    tone="danger"
                    icon={<TrashIcon aria-hidden="true" />}
                    onClick={() => setDeleting(true)}
                  >
                    Delete
                  </ActionLink>
                  {actionError && <HeadAlert>{actionError}</HeadAlert>}
                </>
              )
            }
          />
        }
      />
      {deleting && savedName && (
        <ConfirmDialog
          title={templateDeleteTitle(savedName)}
          confirmLabel="Delete"
          details={TEMPLATE_DELETE_DETAILS}
          onConfirm={() => confirmDelete(savedName)}
          onCancel={() => setDeleting(false)}
        />
      )}
      {blocker !== null && (
        <ConfirmDialog
          title="Leave without saving this listing template?"
          confirmLabel="Leave"
          details="The last complete version stays saved. The changes that made it incomplete are lost."
          onConfirm={blocker.proceed}
          onCancel={blocker.stay}
        />
      )}
    </>
  );
}
