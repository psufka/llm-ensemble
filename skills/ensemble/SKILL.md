---
name: ensemble
description: Run a question through multiple AI CLIs at once (OpenAI Codex, Google Gemini via Antigravity, xAI Grok), compare their answers to your own, and return one synthesized answer. Use when the user says "ensemble [question]", asks for a cross-model second opinion, or wants to fact-check / stress-test a high-stakes decision, claim, or piece of writing. Requires the codex, agy, and grok CLIs to be installed and authenticated.
---

# Ensemble

Run an important question through several frontier models at once, then synthesize a single answer that's better than any one model alone. You (Claude) orchestrate: answer first, fan the same question out to the other CLIs in parallel, compare, and merge.

## Prerequisites — required, not installed by this skill

This skill **assumes the other AI CLIs are already installed and authenticated.** It must never attempt to install them. Before running, verify what's available:

```bash
command -v codex agy grok
```

- If a CLI is missing, **skip that model** and note it in the output.
- If fewer than two external CLIs are available, tell the user the ensemble needs at least two and point them to the install steps in the repo README (`https://github.com/psufka/llm-ensemble`). Do not proceed with a single model and call it an ensemble.

## Steps

When the user says `ensemble [question]` (or asks for a cross-model take):

1. **Answer first.** Write your own best answer before calling anything. The point is to cross-check your judgment, not outsource it.

2. **Detect & report the models — first ensemble of each chat.** Before the first fan-out in a session, determine which model each tool will actually use and **tell the user**, for full transparency:

   > 🧩 Ensemble models this session — Codex: `gpt-5.5` · Gemini: `Gemini 3.1 Pro (High)` · Grok: `grok-build`

   - **Gemini:** run `agy models` and pick the newest non-Flash **Pro** tier (ignore anything labeled Flash / Fast / Lite / mini). **Never hardcode a version — always read it from `agy models`.** If `agy` is missing or the listing fails, skip Gemini for this session.
   - **Codex:** report the active model from `~/.codex/config.toml` (`model = …`) if set, otherwise "CLI default."
   - **Grok:** `grok-build` (the CLI's rolling "latest" default) unless the user has overridden it.

   Reuse these selections for the rest of the session. **Never use a Flash-tier model.**

3. **Fan out in parallel.** Send the **same** prompt to each available CLI concurrently (one batch, not sequentially), from a scratch dir (e.g. `/tmp`) so the agentic CLIs don't index your files. Use the models detected in step 2:

   ```bash
   # OpenAI Codex — --skip-git-repo-check allows non-repo dirs; rides the detected/default model
   codex exec --skip-git-repo-check -c model_reasoning_effort="xhigh" "QUESTION" </dev/null

   # Google Gemini (Antigravity) — pass the model detected via `agy models`; NEVER a hardcoded version
   agy --model "$GEMINI_MODEL" -p "QUESTION" </dev/null

   # xAI Grok — grok-build rolling latest (no version to pin)
   grok -p "QUESTION" --always-approve --disallowed-tools "search_replace,run_terminal_cmd" </dev/null
   ```

   - Use the identical prompt for every model so answers are comparable.
   - **Run each non-interactively** (`</dev/null`) so no CLI blocks waiting on stdin — without it, `agy` hangs indefinitely in a non-TTY / parallel context. If a tool still hangs, kill it and move on.
   - If a CLI errors or is unavailable, proceed with the rest — two responding models is enough.

4. **Compare.** Lay out where all models agree, where they diverge, and any blind spot only one caught. Note confidence.

5. **Synthesize.** Return **one** integrated answer — not a vote tally, not three pasted transcripts. Take the strongest reasoning from each, and explicitly flag any claim the models disagreed on so the user knows where to dig.

## When to use it

- Decisions with real stakes — career, strategy, money
- Fact-checking — if the models agree, a claim is more likely right; if they diverge, dig deeper
- Writing — parallel drafts surface angles one model won't
- Checking your own assumptions — different training biases triangulate blind spots

Skip it for trivial lookups; one model is fine there.
