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
| Answer #2 | **Codex** (OpenAI) | CLI default · xhigh reasoning |
| Answer #3 | **Gemini** (Google) | Gemini 3.1 Pro (non-Flash) |
| Answer #4 | **Grok** (xAI) | `grok-build` (rolling latest) |

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

### 2. Install the skill in Claude

This repo ships a ready-made [Claude Code skill](skills/ensemble/SKILL.md) that handles the whole
orchestration. The easiest way to install it — **copy the following into Claude Code and send it:**

```
Install the "ensemble" skill from github.com/psufka/llm-ensemble: create the folder
~/.claude/skills/ensemble/ and download
https://raw.githubusercontent.com/psufka/llm-ensemble/main/skills/ensemble/SKILL.md
into it as SKILL.md. Then check whether the codex, gemini (or agy), and grok CLIs are
installed and tell me which ones I still need to set up.
```

Restart Claude Code so it loads the new skill — then just say `ensemble <question>`.

**Prefer to install it manually?**

```bash
git clone https://github.com/psufka/llm-ensemble
cp -r llm-ensemble/skills/ensemble ~/.claude/skills/ensemble
```

The skill checks that the `codex`, `agy`/`gemini`, and `grok` CLIs are installed (it never installs
them) and skips any that are missing.

## When to use it

Not everything needs four models. Ensemble for:

- **Decisions with real stakes** — career moves, strategy, money
- **Fact-checking** — if all four agree, it's more likely to be right; if they diverge, dig deeper
- **Writing** — parallel drafts surface angles one model would never give you
- **Checking your assumptions** — each model has different training biases; triangulation exposes yours

For quick questions ("what's the capital of France"), one model is fine.

## Tips & gotchas

- **Avoid Flash-tier models** — `agy` in particular defaults to Gemini Flash; you must pass `--model`
  or you silently get the weak one.
- **Models stay current on their own** — Codex and Grok ride their CLIs' rolling defaults, and the skill
  runs `agy models` once per session to lock in the newest non-Flash Gemini Pro — so it tracks new
  releases without re-checking on every call.

## Credit

Inspired by Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council).
