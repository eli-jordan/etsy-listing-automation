/** Narrows away `undefined`/`null` in tests without the `!` non-null
 * assertion operator (forbidden by this repo's eslint config) -- throws with
 * a clear message if the value genuinely isn't there, which is a better
 * failure than a silent `undefined` propagating into an assertion. */
export function must<T>(value: T | undefined | null): T {
  if (value === undefined || value === null) {
    throw new Error("expected a defined value in test");
  }
  return value;
}
