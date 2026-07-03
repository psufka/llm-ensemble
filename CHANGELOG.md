# Changelog

Notable changes to `llm-ensemble`.

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
