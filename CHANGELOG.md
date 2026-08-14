# Changelog

Notable changes to `llm-ensemble`.

## 2026-08-14

### Added

- Added live Artificial Analysis Intelligence Index resolution. Active models use OpenRouter's public `benchmarks.artificial_analysis` fields; delisted Claude models fall back to their retained Artificial Analysis pages and are marked as estimated configuration matches when the local runtime only says `Thinking`.
- Added intelligence score, coding/agentic sub-scores when present, source URL, matched benchmark model, retrieval time, and estimation status to `MODEL_EVENT` output, leg records, blind-answer mappings, and the top-level prompted-model roster.
- Added Grok installation documentation and explicit `~/.grok/skills/ensemble` support.
- Added Codex reasoning effort to live model resolution, completion summaries, blind mappings, and roster metadata; Codex labels now render as `<model> [<effort>]`, such as `gpt-5.6-sol [max]`.

### Changed

- Claude, Gemini, and Grok model selection now ranks every locally available candidate by the live intelligence index. Product tier names and version/effort heuristics are fallbacks only, so a higher-scoring Flash or Sonnet model can correctly outrank a Pro or Opus model.
- Free OpenRouter selection now ranks by the embedded intelligence index first and no longer rejects models merely because their names contain Flash, Fast, Lite, or Mini.
- The required final roster now includes each exact model's intelligence score, result, and source/retrieval note.

### Fixed

- Replaced the misleading `not indexed` outcome for models omitted from OpenRouter with an Artificial Analysis page fallback and an explicit `score unavailable` result only after lookup fails.

## 2026-08-09

### Added

- Added a user-pinned OpenRouter leg: `--openrouter-model <id>` runs any OpenRouter model (free or paid) as a new `openrouter-pinned` leg **in addition to** the free-model wildcard by default; `--openrouter-swap` makes it **replace** the free leg instead. Plain runs without the flag are unchanged. The pinned model is labeled `<model id> (openrouter pinned)` in events, roster, `status.json`, and blind-answer mapping; it gets no smoke test and no fallback (one retry on retryable upstream errors), and its `max_tokens` is clamped from model metadata via the new `find_model()` lookup (no pricing filter).
- The free-model wildcard now also excludes the pinned model's vendor prefix (pinning `moonshotai/kimi-k3` keeps the free pick away from other Moonshot models); `excluded_by_vendor()` accepts raw `vendor/` prefixes alongside family names.

## 2026-08-04

### Added

- Added blinded comparison as the default workflow: the runner writes valid answers in shuffled order to `answers/answer-N.txt` with identities in a separate `answers/mapping.json` (`BLIND_ANSWERS_DIR`), and the skill compares anonymized answers before unblinding. Unblinded runs happen on user request.
- Added an ensemble-family filter to OpenRouter free-model selection: candidates from vendor families already in the ensemble (orchestrator + active legs) are excluded so the wildcard adds an independent lab. Disable with `--no-openrouter-family-filter`; the standalone selector gained `--exclude-family`.
- Added an opt-in debate round to the skill workflow: proposed only when answers materially disagree on a consequential question (auto-run when the user opts in up front), built from the anonymized round-1 answers.
- Added a single retry for CLI legs on generic failures, reported as a `retry` event; auth, quota/rate-limit, timeout, oversized-prompt, and sandbox failures are not retried.

- Added `--resolve-only` to resolve and announce every leg's exact model without sending the user prompt (fast model-freshness check; `MODE=resolve-only`).
- Added `--skip-leg` / `--only-leg` (repeatable) to control which legs run.
- Added a `finished` `MODEL_EVENT` per leg (with `ok` and duration) so the orchestrator can track progress during long runs.
- Added Codex reasoning-effort resolution from `--codex-effort`, `ENSEMBLE_CODEX_EFFORT`, or the Codex config's `model_reasoning_effort` (previously hardcoded to xhigh, which silently overrode a higher configured effort).
- Added credential-failure classification for Codex and Grok legs (parity with agy): clear login failures now set `requires_user_action` instead of a generic exit-code failure.
- Added OpenRouter truncation detection: `finish_reason=length` marks the leg `"truncated": true` in `status.json` and the tail summary, and `max_tokens` is clamped to the model's completion limit.

### Changed

- Model resolution now runs concurrently inside each leg's worker (previously `agy models` and `grok models` ran serially before any leg started — up to 60s of dead time).
- OpenRouter smoke tests now run concurrently across candidates instead of sequentially (up to ~2 minutes faster startup); passing candidates are still preferred in rank order.
- Claude model ranking now places Mythos/Fable above Opus and recognizes those names without a "Claude" prefix; Gemini ranking places Ultra above Pro.
- Rebalanced OpenRouter free-model scoring: context length is capped at 500 points (was 1000) and reasoning support raised to 400, so a long-context weak model can no longer outrank a strong reasoner on window size alone.
- Raised the default OpenRouter `max_tokens` from 4096 to 16384 (reasoning models spend part of the budget on reasoning tokens).
- The OpenRouter leg now receives the raw user prompt (its API call already carries the answer-only system message; previously the instruction was duplicated).
- Trimmed the skill description frontmatter to reduce per-session context cost.

### Fixed

- Fixed Claude/Gemini selection for agy's new slug-format model listing (`gemini-3.1-pro-high`, `claude-opus-4-6-thinking`): the old parser expected display names ("Gemini 3.1 Pro (High)"), found no tier or version in slugs, and its alphabetical fallback actually selected `gemini-3.1-pro-low` over `-high`. Tier and version now parse from both formats.
- Pinned agy's `--print-timeout` to the leg timeout; agy's 5-minute default silently abandoned longer runs even though the runner allows 10 minutes.
- Timeouts now kill the leg's entire process group (`start_new_session` + `killpg`), so a hung CLI can no longer leave orphaned child processes behind.
- The ensemble output directory is now always created with 0700 permissions, including when `--output-dir` is supplied (it holds the full prompt and model outputs).

## 2026-07-09

### Added

- Added flushed `MODEL_EVENT` startup reporting so the orchestrator can announce each exact model/version as soon as it resolves, before waiting for the ensemble to finish.
- Added `orchestrator_model` and per-leg `models_prompted` tracking to `status.json`, including failed fallback attempts that received the user's prompt.
- Added dynamic Grok default resolution through `grok models` and explicit `--model` pinning.
- Added Codex model resolution through `--codex-model`, `ENSEMBLE_CODEX_MODEL`, or the base Codex config, followed by explicit `-m` pinning.
- Added Claude-via-Antigravity as an external leg when Claude is not the orchestrator.

### Changed

- Required the final synthesis to end with the same exact model/version roster reported during startup.
- Standardized OpenRouter user-facing labels as `<exact model/version> (free)` when the roster already labels the leg as OpenRouter.
- Suppressed “models are resolving” narration; model rows appear only after the exact model/version is known.
- Replaced vague Codex/Grok “CLI default” labels with resolved model IDs; unresolved IDs now skip cleanly rather than claiming an unknown model.

### Fixed

- Prevented OpenRouter model-selection exhaustion from terminating the entire runner before `status.json` is written.
- Added attempt-level success to the prompted-model roster so failed OpenRouter attempts stay labeled when a fallback succeeds.
- Tightened `agy` auth-log matching to avoid false reauthentication prompts.
- Preserved full/degraded synthesis when another leg needs user action but enough valid answers remain.
- Stopped OpenRouter smoke tests after enough passing fallback candidates are found.
- Deduplicated Claude/Gemini discovery so `agy models` runs once per ensemble and both legs reuse the same snapshot.

## 2026-07-03

### Added

- Added `skills/ensemble/scripts/run_ensemble.py` as the structured runner for external ensemble legs.
- Added machine-readable `status.json` output with per-leg model, exit code, duration, stdout/stderr paths, skip reasons, failure reasons, and OpenRouter attempts.
- Added per-run Gemini model selection from `agy models`, preferring Pro over Flash and High over lower tiers.
- Added user-action-required handling for clear `agy` credential failures so Gemini is not silently skipped when Antigravity needs reauthentication.
- Added OpenRouter real-prompt fallback across alternate free models after retryable upstream/capacity failures.

### Changed

- Replaced the fragile shell fan-out snippet in `SKILL.md` with runner-based instructions.
- Removed shell `eval` from the OpenRouter execution path used by the ensemble runner.
- Aligned OpenRouter real-prompt timeout with the runner's 600-second default.
- Updated README with runner output, Codex `$ensemble` invocation, Gemini selection behavior, and `needs-user-action` mode.

### Fixed

- Fixed heredoc/shell interpolation risk by requiring prompt-file based runner execution.
- Fixed empty-PID/no-leg hang risk by moving process orchestration into Python.
- Fixed large `agy -p` prompt handling by recording a clean Gemini failure when the prompt exceeds the configured argument threshold.
- Hardened OpenRouter helper scripts with explicit UTF-8 reads, non-deprecated timestamp handling, and tighter model-size matching.

## 2026-07-02

### Added

- Added runtime-aware orchestration: the skill now identifies whether the current agent is Claude, Codex, Gemini, Grok, OpenRouter, or another LLM before choosing external ensemble legs.
- Added same-family skip logic so the orchestrator does not call its own model family and count it as an independent perspective.
- Added a direct OpenRouter free-model leg using `OPENROUTER_API_KEY`.
- Added `skills/ensemble/scripts/select_openrouter_free_model.py` to rank currently available free OpenRouter text models.
- Added smoke-tested OpenRouter selection with `--smoke` to avoid temporarily rate-limited or weak instruction-following free models.
- Added `skills/ensemble/scripts/openrouter_query.py` for direct OpenRouter chat-completion calls.
- Added Codex-facing skill metadata at `skills/ensemble/agents/openai.yaml`.
- Updated README install instructions for Claude and Codex, including full-folder skill installation.

### Changed

- Claude is now orchestrator-only. Non-Claude orchestrators no longer attempt to spawn `claude --print` as an external ensemble leg.
- OpenRouter is now called directly through its API instead of through OpenCode by default.
- README now describes a dynamic model roster instead of a Claude-only four-model council.
- Skill install instructions now require copying the whole `skills/ensemble` folder because helper scripts are part of the skill.

## 2026-06

### Added

- Initial public README for a command-line LLM ensemble using Claude, Codex, Gemini/Agy, and Grok.
- Added Claude Code skill at `skills/ensemble/SKILL.md`.
- Added model detection for the newest non-Flash Gemini Pro model via `agy models`.
- Added first-run model roster reporting.
- Added support for inlining attached file contents into the shared ensemble prompt.

### Changed

- Unpinned Codex and Grok defaults so their CLIs can track current models.
- Moved verbose flag rationale out of the skill body and into README to keep skill context lighter.
- Raised watchdog timeout from 180 seconds to 600 seconds for deep-reasoning and web-grounded runs.
- Enabled web search for Codex and Grok ensemble legs where supported.

### Fixed

- Added `--skip-git-repo-check` to Codex so runs work from scratch/temp directories.
- Closed stdin with `</dev/null` for non-interactive CLI runs to prevent hangs.
- Replaced Grok's fails-open `--tools ""` pattern with kernel `--sandbox read-only` plus a throwaway cwd.
- Added a guard that discards Grok output if its sandbox profile fails to apply.
- Treated empty stdout as failure for all model CLIs.
- Added Agy log parsing for silent quota/auth/rate-limit failures.
