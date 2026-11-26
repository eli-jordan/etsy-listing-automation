import { useEffect, useRef } from "react";

/** `value` as of the last commit, for a listener that outlives renders. */
export function useLatest<T>(value: T): { readonly current: T } {
  const latest = useRef(value);
  useEffect(() => {
    latest.current = value;
  }, [value]);
  return latest;
}
