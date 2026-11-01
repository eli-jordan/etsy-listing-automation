export function ColourPicker({
  colour,
  colours,
  onChange,
}: {
  colour: string;
  colours: string[];
  onChange: (colour: string) => void;
}) {
  return (
    <label className="app__bar-field">
      <span>Colour</span>
      <select value={colour} onChange={(e) => onChange(e.target.value)}>
        {colours.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </label>
  );
}
