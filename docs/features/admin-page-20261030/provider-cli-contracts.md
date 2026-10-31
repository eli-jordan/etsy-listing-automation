# Provider CLI contracts

PR5 verified the installed CLIs with read-only version, help and catalog
commands on 2026-10-30. No generation or account configuration changes were
needed. These measurements support ADR-0056; discovery remains advisory when
another installed version changes its format.

| CLI | Discovery format | Explicit preferences |
|---|---|---|
| Codex 0.166.0 | `codex debug models` returns a JSON object with `models`. Visible rows use `slug`, `display_name` and `supported_reasoning_levels[].effort`. Hidden rows and ultra effort are omitted from offered choices. | `--model <id>` and `-c model_reasoning_effort="<effort>"`. The installed exec help confirms model and config overrides. |
| Claude Code 2.1.314 | The curated list uses `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`. Fable is excluded. | `--model <id>` and `--effort <level>`. Installed help lists low, medium, high, xhigh and max. |
| Grok 1.0.70 | `grok models` prints a preamble, then `Available models:` with `* id (default)` or `- id` rows. The measured catalog offered grok-4.7, grok-4.7-build-fast, grok-4.6 and grok-4.5. | `--model <id>` and `--reasoning-effort <effort>`, with low, medium and high offered by Admin. |

The curated Claude ids follow the [official model overview](https://platform.claude.com/docs/en/models/overview).
Codex's effort config key follows the [official settings reference](https://learn.chatgpt.com/docs/developer-settings).
The installed `codex features list -c model_reasoning_effort=...` command also
accepted the override syntax without starting generation. Neither catalog
contents nor acceptance of a settings override proves that a later generation
can use a saved choice. CLI rejection remains an allowed fallback condition.

Account default omits the corresponding flag. Explicit choices are passed
unchanged for every task and repair. No adapter passes a service-tier flag.
Subprocess contract tests cover the added argument suffixes and omitted
flags; existing adapter and process tests retain the read-only tools,
noninteractive execution, cancellation and subprocess-tree cleanup checks.

The host attempts discovery at startup. Reads reuse the result for 30 minutes;
the next read after expiry or an explicit Refresh retries discovery. Failure
retains earlier catalog choices with a problem and never edits settings.
The UI always retains saved model and effort choices plus Account default.

Provider enable, disable and order changes use the existing full-candidate,
revision-checked settings transaction. The UI's `AiProviders.onSave` supplies
the complete provider list to that queue. PR6 can include a raised run limit
in the same changes object. PR5 retains the fixed five-minute task and
twenty-minute run defaults.
