/**
 * The opt-in to publish new and still-draft listings on Etsy rather than
 * leave them drafts. Off by default. Changing it plans again, because the
 * apply runs exactly the plan that was reviewed and publishing adds a step
 * to that plan (`etsy_activate`).
 */
export function PublishDraftsToggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (publish: boolean) => void;
}) {
  return (
    <label className="dv-publish">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <strong>Publish new listings on Etsy</strong>
        <span className="dv-publish__hint">
          {checked
            ? "New and draft listings go live once every step has run. Etsy charges its listing fee."
            : "Off: new listings stay Etsy drafts for you to publish yourself."}
        </span>
      </span>
    </label>
  );
}
