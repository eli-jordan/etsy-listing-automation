import { useCallback, useEffect, useRef, useState } from "react";
import { getShopLookups, type ShopLookups } from "../../api/shop";
import { policyKey, type Creatable } from "./shopFields";

/** One option a refresh found that the previous answer did not have. */
export interface Found {
  value: string;
  label: string;
}

function choices(lookups: ShopLookups, field: Creatable): Found[] {
  switch (field) {
    case "production_partner":
      return lookups.etsy.production_partners.map((n) => ({ value: n, label: n }));
    case "shipping_profile":
      return lookups.etsy.shipping_profiles.map((n) => ({ value: n, label: n }));
    case "return_policy":
      return lookups.etsy.return_policies.map((p) => ({
        value: policyKey(p.terms),
        label: p.label,
      }));
    case "preferred_print_provider":
      return lookups.printify.print_providers.map((n) => ({ value: n, label: n }));
  }
}

const FIELDS: Creatable[] = [
  "production_partner",
  "preferred_print_provider",
  "shipping_profile",
  "return_policy",
];

/**
 * The shop's live lists, asked for again whenever the window regains focus
 * (the seller may have created something in the Etsy tab) or on Retry.
 * One request at a time. Nothing here saves: an option a refresh found is
 * only offered (Admin plan, *Shop*). Etsy's lists are never cached on
 * disk server-side either (ADR-0033).
 */
export function useShopLookups() {
  const [lookups, setLookups] = useState<ShopLookups | null>(null);
  const [pending, setPending] = useState(true);
  const [failure, setFailure] = useState<string | null>(null);
  const [found, setFound] = useState<Partial<Record<Creatable, Found>>>({});
  const inFlight = useRef(false);
  const previous = useRef<ShopLookups | null>(null);

  // What an answer does. Every state update lands after the request
  // returns, so mounting can start one from an effect.
  const answered = useCallback((next: ShopLookups) => {
    const before = previous.current;
    if (before) {
      const discovered: Partial<Record<Creatable, Found>> = {};
      for (const field of FIELDS) {
        const known = new Set(choices(before, field).map((c) => c.value));
        const service = field === "preferred_print_provider" ? "printify" : "etsy";
        if (!before[service].available) continue;
        const fresh = choices(next, field).find((c) => !known.has(c.value));
        if (fresh) discovered[field] = fresh;
      }
      setFound((current) => ({ ...current, ...discovered }));
    }
    previous.current = next;
    setLookups(next);
    setFailure(null);
  }, []);
  const failed = useCallback((error: unknown) => {
    setFailure(error instanceof Error ? error.message : "could not look up the shop's lists");
  }, []);
  const settled = useCallback(() => {
    inFlight.current = false;
    setPending(false);
  }, []);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    await getShopLookups().then(answered, failed).finally(settled);
  }, [answered, failed, settled]);

  useEffect(() => {
    inFlight.current = true;
    void getShopLookups().then(answered, failed).finally(settled);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [answered, failed, settled, refresh]);

  const dismiss = useCallback(
    (field: Creatable) =>
      setFound(
        (current) =>
          Object.fromEntries(Object.entries(current).filter(([key]) => key !== field)) as Partial<
            Record<Creatable, Found>
          >,
      ),
    [],
  );

  const etsyAvailable = failure === null && lookups?.etsy.available === true;
  const printifyAvailable = failure === null && lookups?.printify.available === true;
  return {
    lookups,
    pending,
    etsyAvailable,
    printifyAvailable,
    /** The lookups answered, but at least one service could not. */
    failed: (lookups !== null && (!etsyAvailable || !printifyAvailable)) || failure !== null,
    problems: [failure, lookups?.etsy.problem, lookups?.printify.problem].filter((p): p is string =>
      Boolean(p),
    ),
    found,
    dismiss,
    refresh,
    choices: (field: Creatable) => (lookups ? choices(lookups, field) : []),
  };
}
