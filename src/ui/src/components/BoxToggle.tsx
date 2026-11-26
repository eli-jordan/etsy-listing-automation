import { BoundingBoxIcon } from "@phosphor-icons/react/dist/csr/BoundingBox";

export function BoxToggle({
  checked,
  onChange,
  label = "Show design box",
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
}) {
  return (
    <div className="box-toggle" title={label}>
      <BoundingBoxIcon aria-hidden="true" />
      <button
        type="button"
        className="box-toggle__switch"
        role="switch"
        aria-label={label}
        aria-checked={checked}
        onClick={() => onChange(!checked)}
      >
        <i />
      </button>
    </div>
  );
}
