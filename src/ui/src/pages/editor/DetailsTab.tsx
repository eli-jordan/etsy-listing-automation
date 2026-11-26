import { useEffect, useRef, useState } from "react";
import { createEtsySection, listCommonCopy, listEtsySections } from "../../api/listings";
import type { CommonCopySummary, EtsySectionSummary, ListingDetail } from "../../types";
import { AiChoiceDrawer } from "./aiSeo/AiChoiceDrawer";
import { DescriptionSourcePicker } from "./DescriptionSourcePicker";
import { MarketListingsPanel } from "./market/MarketListingsPanel";
import { AiSeoControl } from "./aiSeo/AiSeoControl";
import { AiTagsDrawer } from "./aiSeo/AiTagsDrawer";
import type { AiSeoMode } from "./aiSeo/useAiSeoMode";
import { useDrawerMotion } from "./useDrawerMotion";
import { useIsPhone } from "../../phone/usePhone";

const MAX_TITLE_LENGTH = 140;
const MAX_TAGS = 13;
const CREATE_SECTION_VALUE = "create";

/** `check_copy_is_concrete`/`check_description_ref`
 * (`config/listing_validation.py`) file every description issue -- the empty
 * lead that blocks deployment, and a `ref` that will not resolve -- under
 * this one `where`, matching `_COPY_WHERE["description"]` exactly. Both are
 * shown together beneath the description fields, the same block issues the
 * page-level banner surfaces, but visible without leaving the tab. */
const DESCRIPTION_ISSUE_WHERE = "Listing Details › Description";

type Props = {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: () => void;
} & (
  | {
      kind?: "listing";
      aiSeo: AiSeoMode;
    }
  | {
      kind: "listing-template";
      aiSeo?: undefined;
    }
);

export function DetailsTab(props: Props) {
  const { detail, onUpdate, onFlush } = props;
  const aiSeo = props.kind === "listing-template" ? null : props.aiSeo;
  const phone = useIsPhone();
  const [tagDraft, setTagDraft] = useState("");
  const [sections, setSections] = useState<EtsySectionSummary[]>([]);
  const [sectionsAvailable, setSectionsAvailable] = useState(false);
  const [creatingSection, setCreatingSection] = useState(false);
  const [sectionDraft, setSectionDraft] = useState("");
  const [sectionCreating, setSectionCreating] = useState(false);
  const [sectionCreateError, setSectionCreateError] = useState<string | null>(null);
  const [commonCopy, setCommonCopy] = useState<CommonCopySummary[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const previewButtonRef = useRef<HTMLButtonElement>(null);
  const phase = aiSeo?.phase ?? null;
  const proposal = aiSeo?.proposal ?? null;
  const drawerMotion = useDrawerMotion(phase, proposal !== null);
  const aiModeButtonRef = useRef<HTMLButtonElement>(null);
  const titleDrawerRef = useRef<HTMLDivElement>(null);
  const hadAiSeoProposal = useRef(false);
  const tags = detail.etsy.tags;
  const titleError = detail.field_errors["etsy.title"];
  const sectionError = detail.field_errors["etsy.section"];
  const title = detail.etsy.title;
  const description = detail.etsy.description;
  const descriptionIssues = detail.issues.filter((i) => i.where === DESCRIPTION_ISSUE_WHERE);

  useEffect(() => {
    listEtsySections().then((result) => {
      setSectionsAvailable(result.available);
      setSections(result.sections);
    });
  }, []);

  useEffect(() => {
    listCommonCopy().then(setCommonCopy);
  }, []);

  useEffect(() => {
    if (!previewOpen) return;
    function onPointerDown(event: PointerEvent) {
      if (!previewRef.current?.contains(event.target as Node)) setPreviewOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setPreviewOpen(false);
        previewButtonRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [previewOpen]);

  useEffect(() => {
    const hasProposal = proposal !== null;
    if (hasProposal && !hadAiSeoProposal.current) {
      titleDrawerRef.current?.querySelector<HTMLButtonElement>(".seo-choice-list button")?.focus();
    } else if (!hasProposal && hadAiSeoProposal.current) {
      aiModeButtonRef.current?.focus();
    }
    hadAiSeoProposal.current = hasProposal;
  }, [proposal]);

  function setBodySource(source: string | null) {
    if (source === null) {
      onUpdate({
        etsy: { description: { ...description, text: description.text ?? "", ref: null } },
      });
      return;
    }
    onUpdate({ etsy: { description: { ...description, text: null, ref: source } } });
  }

  function commitTags() {
    const additions = tagDraft
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t !== "" && !tags.includes(t));
    if (additions.length > 0) {
      onUpdate({ etsy: { tags: [...tags, ...additions] } });
    }
    setTagDraft("");
  }

  function removeTag(tag: string) {
    onUpdate({ etsy: { tags: tags.filter((t) => t !== tag) } });
  }

  async function commitSection() {
    const title = sectionDraft.trim();
    if (title === "") return;
    setSectionCreating(true);
    setSectionCreateError(null);
    try {
      const created = await createEtsySection(title);
      setSections((current) => [...current, created]);
      setCreatingSection(false);
      setSectionDraft("");
      onUpdate({ etsy: { section: created.title } });
      onFlush();
    } catch {
      setSectionCreateError("Could not create the section on Etsy. Check your Etsy sign-in.");
    } finally {
      setSectionCreating(false);
    }
  }

  const fields = (
    <div className="details-tab">
      <fieldset className="seo-details-fieldset">
        <legend className="seo-details-legend">Listing details</legend>

        {aiSeo !== null && (
          <>
            <div className="seo-brief-row">
              <div className="field">
                <label htmlFor="details-brief">Brief</label>
                <textarea
                  id="details-brief"
                  placeholder="Describe the design and include any exact words shown in it."
                  value={detail.brief}
                  onChange={(event) => onUpdate({ brief: event.target.value })}
                  onBlur={onFlush}
                />
              </div>
              <AiSeoControl mode={aiSeo} buttonRef={aiModeButtonRef} />
            </div>

            <div className={titleError ? "field field--invalid" : "field"}>
              <label htmlFor="details-title">Title</label>
              <div className="field__line">
                <div className="field__stack">
                  <input
                    id="details-title"
                    className="input"
                    type="text"
                    placeholder="The title shoppers see on Etsy"
                    value={detail.etsy.title}
                    onChange={(event) => onUpdate({ etsy: { title: event.target.value } })}
                    onBlur={onFlush}
                  />
                  {titleError && <span className="field__error">{titleError}</span>}
                  {aiSeo.proposal?.resolution.title === "pending" && (
                    <div ref={titleDrawerRef}>
                      <AiChoiceDrawer
                        enter={drawerMotion}
                        field="title"
                        options={aiSeo.proposal.proposal.titles}
                        staleReason={aiSeo.staleReason}
                        rationale={aiSeo.proposal.proposal.rationale}
                        warnings={aiSeo.proposal.proposal.warnings}
                        observedText={aiSeo.proposal.proposal.observed_text}
                        onChoose={aiSeo.chooseTitle}
                        onReject={aiSeo.rejectTitle}
                      />
                    </div>
                  )}
                </div>
                <span className="field__count">
                  {title.length} / {MAX_TITLE_LENGTH}
                </span>
              </div>
            </div>

            <div className="field">
              <label htmlFor="details-tag-draft">Tags</label>
              <div className="chips">
                {tags.map((tag) => (
                  <span key={tag} className="chip">
                    {tag}
                    <span className="chip__x" onClick={() => removeTag(tag)}>
                      ×
                    </span>
                  </span>
                ))}
                {tags.length === 0 && <span className="chips__empty">No tags yet</span>}
              </div>
              <div className="field__line">
                <div className="field__stack">
                  <input
                    id="details-tag-draft"
                    className="input tag-paste"
                    type="text"
                    placeholder={
                      phone
                        ? "Add tags, comma separated"
                        : "Type or paste tags, comma separated — press Enter to add"
                    }
                    value={tagDraft}
                    onChange={(event) => setTagDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        commitTags();
                      }
                    }}
                    onBlur={commitTags}
                  />
                  {aiSeo.proposal?.resolution.tags === "pending" && (
                    <AiTagsDrawer
                      enter={drawerMotion}
                      tags={aiSeo.proposal.proposal.tags}
                      selected={tags}
                      staleReason={aiSeo.staleReason}
                      rationale={aiSeo.proposal.proposal.rationale}
                      warnings={aiSeo.proposal.proposal.warnings}
                      observedText={aiSeo.proposal.proposal.observed_text}
                      onToggle={aiSeo.toggleTag}
                      onAcceptBest={aiSeo.acceptBestTags}
                      onClose={aiSeo.closeTags}
                    />
                  )}
                </div>
                <span className="field__count">
                  {tags.length} / {MAX_TAGS}
                </span>
              </div>
            </div>

            <div className="field">
              <label htmlFor="details-description-lead">Description Lead</label>
              <textarea
                id="details-description-lead"
                value={description.lead}
                onChange={(event) =>
                  onUpdate({
                    etsy: { description: { ...description, lead: event.target.value } },
                  })
                }
                onBlur={onFlush}
              />
              {aiSeo.proposal?.resolution.lead === "pending" && (
                <AiChoiceDrawer
                  enter={drawerMotion}
                  field="description_lead"
                  options={aiSeo.proposal.proposal.description_leads}
                  staleReason={aiSeo.staleReason}
                  rationale={aiSeo.proposal.proposal.rationale}
                  warnings={aiSeo.proposal.proposal.warnings}
                  observedText={aiSeo.proposal.proposal.observed_text}
                  onChoose={aiSeo.chooseLead}
                  onReject={aiSeo.rejectLead}
                />
              )}
            </div>
          </>
        )}

        <div className={descriptionIssues.length > 0 ? "field field--invalid" : "field"}>
          <label htmlFor="details-description-source">Description Body</label>
          <DescriptionSourcePicker
            value={description.ref ?? null}
            items={commonCopy}
            onSelect={(source) => {
              setBodySource(source);
              onFlush();
            }}
          />

          {description.ref === null && (
            <textarea
              id="details-description-text"
              aria-label="Description body"
              value={description.text ?? ""}
              onChange={(event) =>
                onUpdate({
                  etsy: { description: { ...description, text: event.target.value, ref: null } },
                })
              }
              onBlur={onFlush}
            />
          )}

          {descriptionIssues.map((issue, index) => (
            <span key={index} className="field__error">
              {issue.message}
            </span>
          ))}
          {aiSeo === null && (
            <span className="field__hint">
              Each listing's own description lead is placed above this body.
            </span>
          )}
        </div>

        <div className="description-preview-control" ref={previewRef}>
          <button
            ref={previewButtonRef}
            type="button"
            className="description-preview-control__link"
            aria-expanded={previewOpen}
            aria-controls="details-description-preview"
            onClick={() => setPreviewOpen((open) => !open)}
          >
            Description preview
          </button>
          {previewOpen && (
            <div
              id="details-description-preview"
              className="description-preview-card"
              role="region"
              aria-label="Description preview"
            >
              <strong className="description-preview-card__title">Description preview</strong>
              <p className="description-preview">{detail.description_composed}</p>
            </div>
          )}
        </div>

        <div className={sectionError ? "field field--invalid" : "field"}>
          <label htmlFor="details-section">Section</label>
          {sectionsAvailable ? (
            <select
              id="details-section"
              className="input"
              value={
                creatingSection
                  ? CREATE_SECTION_VALUE
                  : String(
                      sections.find((section) => section.title === detail.etsy.section)?.id ?? "",
                    )
              }
              onChange={(event) => {
                if (event.target.value === CREATE_SECTION_VALUE) {
                  setCreatingSection(true);
                  setSectionCreateError(null);
                  return;
                }
                setCreatingSection(false);
                const selected = sections.find(
                  (section) => String(section.id) === event.target.value,
                );
                onUpdate({ etsy: { section: selected?.title ?? null } });
                onFlush();
              }}
            >
              <option value="">No section</option>
              {sections.map((s) => (
                <option key={s.id} value={String(s.id)}>
                  {s.title}
                </option>
              ))}
              <option value={CREATE_SECTION_VALUE}>Create new section…</option>
            </select>
          ) : (
            <input
              id="details-section"
              className="input"
              type="text"
              value={detail.etsy.section ?? ""}
              onChange={(event) => onUpdate({ etsy: { section: event.target.value || null } })}
              onBlur={onFlush}
            />
          )}
          {creatingSection && (
            <form
              className="section-create"
              onSubmit={(event) => {
                event.preventDefault();
                void commitSection();
              }}
            >
              <label htmlFor="details-new-section">New section name</label>
              <input
                id="details-new-section"
                className="input"
                type="text"
                autoFocus
                value={sectionDraft}
                onChange={(event) => setSectionDraft(event.target.value)}
              />
              <button
                className="btn btn-primary"
                type="submit"
                disabled={sectionCreating || sectionDraft.trim() === ""}
              >
                {sectionCreating ? "Creating…" : "Create section"}
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                disabled={sectionCreating}
                onClick={() => {
                  setCreatingSection(false);
                  setSectionDraft("");
                  setSectionCreateError(null);
                }}
              >
                Cancel
              </button>
              {sectionCreateError && (
                <span className="field__error" role="alert">
                  {sectionCreateError}
                </span>
              )}
            </form>
          )}
          {sectionError && <span className="field__error">{sectionError}</span>}
        </div>
      </fieldset>
    </div>
  );

  // The top listings panel sits beside the fields once there is a search to
  // show (docs/features/market-seo-20260924/interactions.md, section 3). Without one the
  // fields keep their own width: an empty "run AI Mode" card would be noise
  // on every new listing. The wrapper is there either way, so the fields are
  // never remounted -- losing the seller's focus and caret -- when research
  // starts mid-edit and the panel appears.
  return (
    <div className={aiSeo === null || aiSeo.market === null ? undefined : "mkt-layout"}>
      {fields}
      {aiSeo !== null && aiSeo.market !== null && (
        <MarketListingsPanel state={aiSeo.market} proposal={aiSeo.proposal?.proposal ?? null} />
      )}
    </div>
  );
}
