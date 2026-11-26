export function PublishDraftsToggle({
  checked,
  disabled,
  onChange,
  goingLive,
  single = false,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (publish: boolean) => void;
  goingLive: readonly string[];
  single?: boolean;
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
        <strong>{single ? "Publish on Etsy" : "Publish new listings on Etsy"}</strong>
        <span className="dv-publish__hint">{hint(checked, goingLive.length, single)}</span>
        {checked && !single && (
          <ul className="dv-publish__list" aria-label="Listings that go live">
            {goingLive.map((listing) => (
              <li key={listing}>{listing}</li>
            ))}
          </ul>
        )}
      </span>
    </label>
  );
}

function hint(checked: boolean, count: number, single: boolean): string {
  if (single) {
    return checked
      ? "It goes live once every step has run. Etsy charges its listing fee."
      : "Off: it stays an Etsy draft for you to publish yourself.";
  }
  if (!checked) {
    return `Off: new listings stay Etsy drafts for you to publish yourself. On, ${count} would go live.`;
  }
  return count === 1
    ? "This listing goes live once every step has run. Etsy charges its listing fee."
    : `These ${count} listings go live once every step has run. Etsy charges its listing fee for each.`;
}
