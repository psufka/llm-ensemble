# llm-ensemble

**Run every important question through four AI CLIs at once — then synthesize one better answer.**

Single-model AI is a flashlight. A multi-model *ensemble* is a floodlight: same effort, fewer blind spots.

This is how I run an "LLM council" from the command line. Inspired by Andrej Karpathy's
[llm-council](https://github.com/karpathy/llm-council), but stripped down to four CLI tools and one instruction.

## The idea

Every model has blind spots. Ask one and you get one perspective. Ask four and compare — where they
agree is more likely right; where they diverge is where to dig. **Claude orchestrates:** it answers first,
then calls the other three as shell commands, compares all four, and synthesizes a single answer.

## The four models

| Role | Tool | Model I run |
|---|---|---|
| Orchestrator + answer #1 | **Claude Code** (Anthropic) | your Claude plan/key |
| Answer #2 | **Codex** (OpenAI) | `gpt-5.5`, xhigh reasoning |
| Answer #3 | **Gemini** (Google) | Gemini 3.1 Pro |
| Answer #4 | **Grok** (xAI) | `grok-build` |

## Setup

### 1. Install the CLIs

These three install cleanly from npm (Node.js required):

```bash
npm install -g @anthropic-ai/claude-code   # orchestrator
npm install -g @openai/codex               # Codex
npm install -g @google/gemini-cli          # Gemini (simple, reproducible path)
```

My actual Gemini + Grok setup uses two more tools, installed via their own installers (not npm):

```bash
# Gemini → Google Antigravity (agy) — better model routing than the base gemini-cli
curl -fsSL https://antigravity.google/cli/install.sh | bash   # installs `agy` to ~/.local/bin

# Grok → xAI Grok CLI
curl -fsSL https://x.ai/cli/install.sh | bash                 # installs `grok`
```

- `@google/gemini-cli` (npm, above) is the fully-reproducible Gemini fallback if you don't want Antigravity.
- Grok: sign in at grok.com on first run (or set `XAI_API_KEY` for headless use).

Each tool prompts for auth on first run (Anthropic / OpenAI / Google / xAI).

### 2. Teach Claude to orchestrate

Add this to your Claude Code memory (`MEMORY.md` or `CLAUDE.md`) so it persists across sessions —
explain it once, and `ensemble` just works every time:

```
When I say "ensemble [question]":
1. Generate your own answer first.
2. In parallel, send the SAME question to Codex, Gemini, and Grok via their CLIs.
3. Compare where all four agree vs. diverge — flag blind spots and confidence.
4. Return ONE synthesized answer, not a vote tally.

Run each from a scratch dir (e.g. /tmp) so the agentic CLIs don't index your files:
  Codex:  codex exec -m gpt-5.5 -c model_reasoning_effort="xhigh" "QUESTION"
  Gemini: agy --model "Gemini 3.1 Pro (High)" -p "QUESTION"
          # fallback: gemini --skip-trust -m gemini-3.1-pro-preview -p "QUESTION"
  Grok:   grok -p "QUESTION" --always-approve --disallowed-tools "search_replace,run_terminal_cmd"

2 of the 3 other models is enough if one errors. Never use Flash-tier models.
```

That's it. Say `ensemble <question>` and Claude does the rest.

### Shortcut: install the bundled skill

Instead of pasting that instruction, drop the bundled [Claude Code skill](skills/ensemble/SKILL.md) into your skills directory:

```bash
git clone https://github.com/psufka/llm-ensemble
cp -r llm-ensemble/skills/ensemble ~/.claude/skills/ensemble
```

Then say `ensemble <question>` in Claude Code. The skill checks that the `codex`, `agy`/`gemini`, and `grok` CLIs are installed (it won't install them) and skips any that are missing.

## When to use it

Not everything needs four models. Ensemble for:

- **Decisions with real stakes** — career moves, strategy, money
- **Fact-checking** — if all four agree, it's more likely to be right; if they diverge, dig deeper
- **Writing** — parallel drafts surface angles one model would never give you
- **Checking your assumptions** — each model has different training biases; triangulation exposes yours

For quick questions ("what's the capital of France"), one model is fine.

## Tips & gotchas

- **Model IDs drift** — re-check the best model for each tool occasionally and update the IDs above.
- **Avoid Flash-tier models** — `agy` in particular defaults to Gemini Flash; you must pass `--model`
  or you silently get the weak one.

## Credit

Inspired by Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council).
