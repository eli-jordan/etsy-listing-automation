import { useEffect, useState } from "react";

const RELATIVE_TIME_TICK_MS = 15_000;

export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), RELATIVE_TIME_TICK_MS);
    return () => clearInterval(id);
  }, []);
  return now;
}
