/**
 * Fixture answers for the few reads the real editor chrome makes on mount
 * (`AppShell`'s shop name, `DeployControl`'s current run), so frames can mount
 * the app's own components without a server. `api/client.ts` captures
 * `globalThis.fetch` when it is created, so this module must be imported
 * before anything that imports the client -- first line of the layout and the
 * screen. Anything else answers 404, which every caller already treats as
 * "nothing there".
 */
const answers: Record<string, unknown> = {
  "/api/workspace": { shop_name: "Pine & Thread" },
  "/api/runs": [],
};

const realFetch = globalThis.fetch.bind(globalThis);

globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
  if (!url.pathname.startsWith("/api/")) return realFetch(input, init);
  const body = answers[url.pathname];
  return new Response(JSON.stringify(body ?? { detail: "not in the mockup" }), {
    status: body === undefined ? 404 : 200,
    headers: { "Content-Type": "application/json" },
  });
};

export {};
