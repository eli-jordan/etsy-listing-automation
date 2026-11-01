import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { SparkleIcon } from "@phosphor-icons/react/dist/csr/Sparkle";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { type ReactNode, useRef, useState } from "react";
import type { SaveOutcome, ShopChanges, ShopSettings } from "../../api/shop";
import { Info, type InfoState } from "./Info";
import {
  CREATE_LINKS,
  type Creatable,
  describeTerms,
  IS_SUPPLY,
  isPrintOnDemand,
  labelOf,
  type Option,
  policyKey,
  PRINT_ON_DEMAND,
  RENEWAL,
  WHEN_MADE,
  WHO_MADE,
} from "./shopFields";
import type { useShopLookups } from "./useShopLookups";
import type { FieldErrors } from "./useShopSettings";

type Lookups = ReturnType<typeof useShopLookups>;
type Save = (changes: ShopChanges) => Promise<SaveOutcome | null>;
/** How a field's intent was answered: written, already held by the file,
 * refused by validation, or not known to have reached the file. */
type Answer = "saved" | "unchanged" | "refused" | "failed";
type CommitOptions = { unchanged?: boolean };
type Commit = (changes: ShopChanges, options?: CommitOptions) => Promise<Answer>;

/**
 * Listing defaults (interactions, *Listing defaults, info cards and
 * external lists*). Print on demand is derived from three saved values and
 * writes all three in one save; Custom shows their selectors and changes
 * nothing by itself. Every selector saves on blur, once, and only a change.
 * Lists come from live lookups; a saved choice they lack stays visible.
 * Mounted afresh for each loaded file, so a reload drops local drafts.
 * Shows `shop` with the queue's pending values over it: what the file will
 * hold once sent saves land, which a newer choice is compared against.
 */
export function ListingDefaults({
  shop: saved,
  pending,
  save,
  discard,
  fieldErrors,
  locked,
  lookups,
  info,
}: {
  shop: ShopSettings;
  pending: ShopChanges;
  save: Save;
  discard: (changes: ShopChanges) => void;
  fieldErrors: FieldErrors;
  locked: boolean;
  lookups: Lookups;
  info: InfoState;
}) {
  const shop = held(saved, pending);
  const defaults = shop.listing_defaults;
  const [customChosen, setCustomChosen] = useState(false);
  const tier = customChosen || !isPrintOnDemand(defaults) ? "custom" : "pod";
  const commit: Commit = (changes, { unchanged = false } = {}) => {
    if (unchanged) {
      discard(changes);
      return Promise.resolve("unchanged");
    }
    return save(changes).then(
      (outcome): Answer =>
        outcome?.kind === "saved" ? "saved" : outcome?.kind === "invalid" ? "refused" : "failed",
      (): Answer => "failed",
    );
  };

  const choosePod = () => {
    setCustomChosen(false);
    void commit(PRINT_ON_DEMAND, { unchanged: isPrintOnDemand(defaults) });
  };
  const customCommit: Commit = (changes, options) => {
    // Editing one of the three keeps Custom open even if the values come
    // to match Print on demand; reopening the page derives it again.
    setCustomChosen(true);
    return commit(changes, options);
  };

  const policies = lookups.lookups?.etsy.return_policies ?? [];

  return (
    <section className="b-panel" aria-labelledby="sp-defaults">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="sp-defaults">
            Listing defaults
          </h2>
          <p className="b-panel__lede">
            What every listing is set up with on Etsy, unless its own file says otherwise.
          </p>
        </div>
      </div>

      <span className="sd-label__name sp-tier-label">
        How your items are made <Info field="tier" info={info} />
      </span>
      <div className="sa-tiers" role="radiogroup" aria-label="How your items are made">
        {(
          [
            ["pod", "Print on demand", choosePod],
            ["custom", "Custom", () => setCustomChosen(true)],
          ] as const
        ).map(([id, label, choose]) => (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={tier === id}
            disabled={locked}
            className={tier === id ? "sa-tier is-on" : "sa-tier"}
            onClick={() => tier !== id && choose()}
          >
            <span className={tier === id ? "sa-radio is-on" : "sa-radio"} />
            {label}
            {id === "pod" && <span className="sa-reco">Recommended</span>}
          </button>
        ))}
      </div>

      {tier === "pod" ? (
        <dl className="sd-set" aria-label="What Print on demand sets">
          {(
            [
              ["who_made", "Who made it", labelOf(WHO_MADE, defaults.who_made)],
              ["when_made", "When it was made", labelOf(WHEN_MADE, defaults.when_made)],
              ["is_supply", "What it is", labelOf(IS_SUPPLY, String(defaults.is_supply))],
            ] as const
          ).map(([field, label, value]) => (
            <div key={field} className="sd-set__row">
              <dt>
                <span className="sd-label__name">
                  {label} <Info field={field} info={info} />
                </span>
              </dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="sa-fields sd-custom sd-custom--3">
          <Field label="Who made it" field="who_made" info={info} error={fieldErrors.who_made}>
            <BlurSelect
              label="Who made it"
              saved={defaults.who_made}
              pending={"who_made" in pending}
              options={withSaved(WHO_MADE, defaults.who_made)}
              disabled={locked}
              onCommit={(value, options) => customCommit({ who_made: value }, options)}
            />
          </Field>
          <Field
            label="When it was made"
            field="when_made"
            info={info}
            error={fieldErrors.when_made}
          >
            <BlurSelect
              label="When it was made"
              saved={defaults.when_made}
              pending={"when_made" in pending}
              options={withSaved(WHEN_MADE, defaults.when_made)}
              disabled={locked}
              onCommit={(value, options) => customCommit({ when_made: value }, options)}
            />
          </Field>
          <Field label="What it is" field="is_supply" info={info} error={fieldErrors.is_supply}>
            <BlurSelect
              label="What it is"
              saved={String(defaults.is_supply)}
              pending={"is_supply" in pending}
              options={IS_SUPPLY}
              disabled={locked}
              onCommit={(value, options) => customCommit({ is_supply: value === "true" }, options)}
            />
          </Field>
        </div>
      )}

      <h3 className="sa-subhead">Fulfilment and policies</h3>
      <div className="sp-discovery">
        <span role="status">
          {lookups.pending
            ? "Refreshing Etsy and Printify lists…"
            : lookups.failed
              ? `Could not reach ${unreachable(lookups)}. Saved choices are shown.`
              : "Lists refresh when you return to this window."}
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={lookups.pending}
          onClick={() => void lookups.refresh()}
        >
          {lookups.pending ? "Refreshing…" : lookups.failed ? "Retry lookups" : "Refresh lists"}
        </button>
      </div>
      {lookups.failed && !lookups.pending && (
        <div className="adm-warn sp-notice" role="alert">
          <WarningOctagonIcon size={18} />
          <span>
            Your defaults have not changed. Retry to load available choices. You can still edit
            renewal and how your items are made.
            {/* The server's reasons can name files and setup steps; they are
                for whoever wants them, not the sentence everyone reads. */}
            {lookups.problems.length > 0 && (
              <details className="sp-problems">
                <summary>Details</summary>
                {lookups.problems.map((problem) => (
                  <p key={problem}>{problem}</p>
                ))}
              </details>
            )}
          </span>
        </div>
      )}

      <div className="sa-fields">
        <ListField
          label="Production partner"
          field="production_partner"
          pending={"production_partner" in pending}
          saved={defaults.production_partner ?? ""}
          savedLabel={defaults.production_partner ?? ""}
          empty="Not set"
          lookups={lookups}
          available={lookups.etsyAvailable}
          {...{ info, locked, fieldErrors, save: commit }}
          toChange={(value) => ({ production_partner: value || null })}
        />
        <ListField
          label="Preferred print provider"
          field="preferred_print_provider"
          pending={"preferred_print_provider" in pending}
          saved={shop.preferred_print_provider ?? ""}
          savedLabel={shop.preferred_print_provider ?? ""}
          empty="No preference"
          lookups={lookups}
          available={lookups.printifyAvailable}
          {...{ info, locked, fieldErrors, save: commit }}
          toChange={(value) => ({ preferred_print_provider: value || null })}
        />
        <ListField
          label="Shipping profile"
          field="shipping_profile"
          pending={"shipping_profile" in pending}
          saved={defaults.shipping_profile ?? ""}
          savedLabel={defaults.shipping_profile ?? ""}
          empty="Not set"
          lookups={lookups}
          available={lookups.etsyAvailable}
          {...{ info, locked, fieldErrors, save: commit }}
          toChange={(value) => ({ shipping_profile: value || null })}
        />
        <ListField
          label="Return policy"
          field="return_policy"
          pending={"return_policy" in pending}
          saved={policyKey(defaults.return_policy)}
          savedLabel={defaults.return_policy ? describeTerms(defaults.return_policy) : ""}
          empty="Not set"
          lookups={lookups}
          available={lookups.etsyAvailable}
          {...{ info, locked, fieldErrors, save: commit }}
          toChange={(value) => ({
            return_policy:
              policies.find((p) => policyKey(p.terms) === value)?.terms ??
              (value === policyKey(defaults.return_policy) ? defaults.return_policy : null),
          })}
        />
        <Field label="Renewal" field="renewal" info={info} error={fieldErrors.renewal}>
          <BlurSelect
            label="Renewal"
            saved={defaults.renewal}
            pending={"renewal" in pending}
            options={withSaved(RENEWAL, defaults.renewal)}
            disabled={locked}
            onCommit={(value, options) => commit({ renewal: value }, options)}
          />
        </Field>
      </div>
      <p className="sd-refresh">
        Made something new on Etsy? The lists refresh when you come back to this tab.
      </p>
    </section>
  );
}

function held(shop: ShopSettings, pending: ShopChanges): ShopSettings {
  const { currency, preferred_print_provider, ...defaults } = pending;
  return {
    ...shop,
    currency: currency ?? shop.currency,
    preferred_print_provider:
      "preferred_print_provider" in pending
        ? (preferred_print_provider ?? null)
        : shop.preferred_print_provider,
    listing_defaults: {
      ...shop.listing_defaults,
      ...(defaults as Partial<ShopSettings["listing_defaults"]>),
    },
  };
}

function unreachable(lookups: Lookups): string {
  if (lookups.lookups === null || (!lookups.etsyAvailable && !lookups.printifyAvailable))
    return "Etsy or Printify";
  return lookups.etsyAvailable ? "Printify" : "Etsy";
}

function withSaved(options: Option[], saved: string): Option[] {
  return options.some((o) => o.value === saved)
    ? options
    : [...options, { value: saved, label: saved }];
}

function Field({
  label,
  field,
  info,
  error,
  create,
  children,
}: {
  label: string;
  field: string;
  info: InfoState;
  error?: string | undefined;
  create?: Creatable;
  children: ReactNode;
}) {
  return (
    <div className="sa-field">
      <span className="sd-label">
        <span className="sd-label__name">
          {label} <Info field={field} info={info} />
        </span>
        {create && (
          <a
            className="sd-create"
            href={CREATE_LINKS[create].href}
            target="_blank"
            rel="noopener noreferrer"
          >
            {CREATE_LINKS[create].label} <ArrowSquareOutIcon size={12} weight="bold" />
          </a>
        )}
      </span>
      {children}
      {error && <p className="adm-error-text">{error}</p>}
    </div>
  );
}

function ListField({
  label,
  field,
  saved,
  pending,
  savedLabel,
  empty,
  lookups,
  available,
  info,
  locked,
  fieldErrors,
  save,
  toChange,
}: {
  label: string;
  field: Creatable;
  saved: string;
  pending: boolean;
  savedLabel: string;
  empty: string;
  lookups: Lookups;
  available: boolean;
  info: InfoState;
  locked: boolean;
  fieldErrors: FieldErrors;
  save: Commit;
  toChange: (value: string) => ShopChanges;
}) {
  const found = lookups.found[field];
  const choices = available ? lookups.choices(field) : [];
  const options: Option[] = choices.map((c) => ({
    value: c.value,
    label: found?.value === c.value ? `${c.label}  · new` : c.label,
  }));
  const missing = saved !== "" && !options.some((o) => o.value === saved);
  if (missing) options.push({ value: saved, label: savedLabel });
  if (saved === "") options.unshift({ value: "", label: empty });
  const where = CREATE_LINKS[field].where;
  // Use it is a choice in this field like any other: it goes through the
  // field's draft, so it supersedes an older draft and a newer one survives
  // its answer.
  const draft = useDraft(saved, pending, (value, options) => {
    if (found?.value === value) lookups.dismiss(field);
    return save(toChange(value), options);
  });
  return (
    <Field label={label} field={field} info={info} error={fieldErrors[field]} create={field}>
      <DraftSelect label={label} options={options} disabled={locked || !available} draft={draft} />
      {available && missing && (
        <span className="sp-missing">
          <WarningIcon size={12} weight="bold" /> {savedLabel} is not in the list {where} returned.
          It stays saved until you choose another.
        </span>
      )}
      {available && found && found.value !== saved && (
        <span className="sd-found">
          <SparkleIcon size={13} weight="fill" /> New from {where}: {found.label}
          <button
            type="button"
            className="sp-use"
            disabled={locked}
            onClick={() => draft.choose(found.value)}
          >
            Use it
          </button>
        </span>
      )}
    </Field>
  );
}

type Draft = {
  shown: string;
  /** The seller changed the select; nothing is sent yet. */
  change: (value: string) => void;
  /** The seller left the select: send its draft if it changes the file. */
  leave: () => void;
  /** A choice made and sent at once, such as Use it. */
  choose: (value: string) => void;
};

/**
 * One field's local edit and the identity of the saves made from it.
 *
 * `saved` is what the file will hold once sent saves land, so a draft is
 * sent only when it differs from that. Each save carries the edit it was
 * made from, and only its own answer drops the draft, and only if nothing
 * was chosen since: an older answer never replaces a newer choice, focused
 * or already queued. A failed save keeps the draft to be sent again on the
 * next leave; a refused one stays shown with its error until the seller
 * picks another or reloads. Every writer of the field (the select and
 * Use it) goes through here, so a newer choice from either supersedes an
 * older draft.
 */
function useDraft(
  saved: string,
  pending: boolean,
  onCommit: (value: string, options?: CommitOptions) => Promise<Answer>,
): Draft {
  const [draft, setDraft] = useState<string | null>(null);
  const edits = useRef(0);
  const sent = useRef<{ value: string; edit: number } | null>(null);
  const refused = useRef<string | null>(null);

  const edit = (value: string) => {
    edits.current += 1;
    refused.current = null;
    setDraft(value);
  };
  const send = (value: string) => {
    // Matching an unanswered write is not acknowledgement of this draft.
    // Keep its save identity until the real outcome, without writing twice.
    if (value === refused.current || (pending && value === saved)) return;
    const mine = { value, edit: edits.current };
    sent.current = mine;
    // An unchanged choice still abandons an older failed patch in the queue.
    void onCommit(value, { unchanged: value === saved }).then((answer) => {
      if (sent.current !== mine) return;
      sent.current = null;
      if (answer === "refused") refused.current = mine.value;
      else if ((answer === "saved" || answer === "unchanged") && edits.current === mine.edit)
        setDraft(null);
    });
  };
  return {
    shown: draft ?? saved,
    change: edit,
    leave: () => {
      if (draft !== null) send(draft);
    },
    choose: (value) => {
      edit(value);
      send(value);
    },
  };
}

/** A select that saves on blur, for a field with no other writer. */
function BlurSelect({
  label,
  saved,
  pending,
  options,
  disabled,
  onCommit,
}: {
  label: string;
  saved: string;
  pending: boolean;
  options: Option[];
  disabled: boolean;
  onCommit: (value: string, options?: CommitOptions) => Promise<Answer>;
}) {
  const draft = useDraft(saved, pending, onCommit);
  return <DraftSelect label={label} options={options} disabled={disabled} draft={draft} />;
}

/** Changing the select only changes what it shows; leaving it saves. */
function DraftSelect({
  label,
  options,
  disabled,
  draft,
}: {
  label: string;
  options: Option[];
  disabled: boolean;
  draft: Draft;
}) {
  return (
    <select
      className="adm-select"
      aria-label={label}
      disabled={disabled}
      value={draft.shown}
      onChange={(e) => draft.change(e.target.value)}
      onBlur={draft.leave}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
