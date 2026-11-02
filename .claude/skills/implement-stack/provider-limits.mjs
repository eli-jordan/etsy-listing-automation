#!/usr/bin/env node
// Prints the subscription headroom of the three delegate providers as JSON:
//
//   node .claude/skills/implement-stack/provider-limits.mjs
//
// Each provider reports {available, windows: [{name, usedPercent, resetsAt}],
// error?}. `available` is false when any window is at or above 90% used or the
// provider says it is blocked. The sources are the ones T3 Code's Usage page
// reads:
//
// - Claude: the Agent SDK's usage control request. The SDK is installed once
//   into ~/.cache/provider-limits; set CLAUDE_BIN if `claude` is not on PATH.
// - Codex: `account/rateLimits/read` on `codex app-server`.
// - Grok: the grok.com billing endpoint, with the `grok login` token from
//   ~/.grok/auth.json (or GROK_HOME). The token is never printed.
//
// A provider whose probe fails reports available: null with the error, so the
// caller can tell "out of quota" from "could not check".
import { execFileSync, execSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const BLOCKED_AT = 90;
const TIMEOUT_MS = 30_000;

function summarise(windows, blocked = false) {
  const full = windows.some((w) => w.usedPercent >= BLOCKED_AT);
  return { available: !blocked && !full, windows };
}

function withTimeout(promise, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out`)), TIMEOUT_MS).unref(),
    ),
  ]);
}

function which(name) {
  const finder = process.platform === "win32" ? "where" : "which";
  try {
    const paths = execFileSync(finder, [name], { encoding: "utf8" }).split(/\r?\n/).filter(Boolean);
    return paths.find((p) => p.endsWith(".exe")) ?? paths[0];
  } catch {
    return undefined;
  }
}

async function claude() {
  const cache = join(homedir(), ".cache", "provider-limits");
  const sdk = join(cache, "node_modules", "@anthropic-ai", "claude-agent-sdk", "sdk.mjs");
  if (!existsSync(sdk)) {
    mkdirSync(cache, { recursive: true });
    execSync(`npm install --prefix "${cache}" --silent @anthropic-ai/claude-agent-sdk`, { stdio: "ignore" });
  }
  const { query } = await import(pathToFileURL(sdk).href);
  const executable = process.env.CLAUDE_BIN || which("claude");
  const abort = new AbortController();
  // A prompt that never yields: only initialization and the usage read happen,
  // so no request reaches the model.
  const prompt = (async function* () {
    await new Promise((resolve) => abort.signal.addEventListener("abort", resolve));
  })();
  const q = query({
    prompt,
    options: { abortController: abort, ...(executable && { pathToClaudeCodeExecutable: executable }) },
  });
  try {
    await q.initializationResult();
    const usage = await q.usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET();
    if (!usage.rate_limits_available) throw new Error("account reports no rate limits");
    const limits = usage.rate_limits?.limits ?? [];
    const windows = limits.map((l) => ({ name: l.kind, usedPercent: l.percent, resetsAt: l.resets_at }));
    const locked = Object.values(usage.rate_limits ?? {}).some((w) => w?.locked_reason);
    return summarise(windows, locked);
  } finally {
    abort.abort();
  }
}

function codex() {
  return new Promise((resolve, reject) => {
    const child = spawn("codex app-server", { shell: true });
    let buffer = "";
    child.on("error", reject);
    child.stdout.on("data", (chunk) => {
      buffer += chunk;
      for (const line of buffer.split("\n").slice(0, -1)) {
        const message = JSON.parse(line);
        if (message.id !== 2) continue;
        child.kill();
        if (message.error) return reject(new Error(message.error.message));
        const limits = message.result.rateLimits;
        const windows = [
          ["five_hour", limits.primary],
          ["weekly", limits.secondary],
        ]
          .filter(([, w]) => w)
          .map(([name, w]) => ({
            name,
            usedPercent: w.usedPercent,
            resetsAt: new Date(w.resetsAt * 1000).toISOString(),
          }));
        resolve(summarise(windows, Boolean(limits.rateLimitReachedType) || limits.spendControlReached));
      }
      buffer = buffer.slice(buffer.lastIndexOf("\n") + 1);
    });
    const send = (m) => child.stdin.write(JSON.stringify({ jsonrpc: "2.0", ...m }) + "\n");
    send({ id: 1, method: "initialize", params: { clientInfo: { name: "provider-limits", version: "1" } } });
    send({ method: "initialized" });
    send({ id: 2, method: "account/rateLimits/read" });
  });
}

async function grok() {
  const home = process.env.GROK_HOME || join(homedir(), ".grok");
  const credentials = JSON.parse(readFileSync(join(home, "auth.json"), "utf8"));
  const credential =
    credentials["https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"] ??
    credentials["https://accounts.x.ai/sign-in"];
  if (!credential?.key) throw new Error("no grok.com login; run `grok login`");
  const response = await fetch("https://cli-chat-proxy.grok.com/v1/billing?format=credits", {
    headers: { Authorization: `Bearer ${credential.key}` },
  });
  if (!response.ok) throw new Error(`billing request failed: HTTP ${response.status}`);
  const { config } = await response.json();
  return summarise([
    { name: "billing_period", usedPercent: config.creditUsagePercent, resetsAt: config.billingPeriodEnd },
  ]);
}

const probes = { claude, codex, grok };
const results = {};
await Promise.all(
  Object.entries(probes).map(async ([name, probe]) => {
    try {
      results[name] = await withTimeout(probe(), name);
    } catch (error) {
      results[name] = { available: null, windows: [], error: String(error.message ?? error) };
    }
  }),
);
console.log(JSON.stringify(results, null, 2));
process.exit(0);
