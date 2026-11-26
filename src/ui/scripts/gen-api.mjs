// Generates src/api/schema.ts from docs/openapi.json (ADR-0011), or with
// --check fails when the committed file differs from what it would generate.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";
import { format, resolveConfig } from "prettier";

const contract = new URL("../../../docs/openapi.json", import.meta.url);
const schema = fileURLToPath(new URL("../src/api/schema.ts", import.meta.url));

const generated = await format(COMMENT_HEADER + astToString(await openapiTS(contract)), {
  ...(await resolveConfig(schema)),
  filepath: schema,
});

if (!process.argv.includes("--check")) {
  await writeFile(schema, generated);
} else if ((await readFile(schema, "utf8")) !== generated) {
  console.error("src/api/schema.ts is stale: run `npm run gen:api` in src/ui.");
  process.exit(1);
}
