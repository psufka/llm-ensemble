# llm-ensemble

**Run every important question through four AI CLIs at once — then synthesize one better answer.**

Single-model AI is a flashlight. A multi-model *ensemble* is a floodlight: same effort, fewer blind spots.

This is how I run an "LLM council" from the command line. Inspired by Andrej Karpathy's
[llm-council](https://github.com/karpathy/llm-council), but stripped down to four CLI tools and a drop-in skill.

## The idea

Every model has blind spots. Ask one and you get one perspective. Ask four — from four *different labs* —
and their blind spots don't overlap the way models from a single vendor would. Where they agree, a claim is
more likely right (agreement is evidence, not proof — models can still err in correlated ways); where they
diverge is where to dig. **Claude orchestrates:** it answers first, then runs the other three as shell
commands, compares all four, and synthesizes one answer.

## The four models

| Role | Tool | Model I run |
|---|---|---|
| Orchestrator + answer #1 | **Claude Code** (Anthropic) | your Claude plan/key |
| Answer #2 | **Codex** (OpenAI) | CLI default · xhigh reasoning |
| Answer #3 | **Gemini** (Google, via Antigravity) | newest non-Flash Pro (auto-detected) |
| Answer #4 | **Grok** (xAI) | `grok-build` (rolling latest) |

## Setup

### 1. Install the CLIs

Claude Code and Codex install from npm (Node.js required):

```bash
npm install -g @anthropic-ai/claude-code   # orchestrator
npm install -g @openai/codex               # Codex
```

Gemini and Grok install via their own installers:

```bash
# Gemini → Google Antigravity (agy)
curl -fsSL https://antigravity.google/cli/install.sh | bash   # installs `agy` to ~/.local/bin

# Grok → xAI Grok CLI
curl -fsSL https://x.ai/cli/install.sh | bash                 # installs `grok`
```

Grok: sign in at grok.com on first run (or set `XAI_API_KEY` for headless use). Each tool prompts for
auth on first run (Anthropic / OpenAI / Google / xAI).

### 2. Install the skill in Claude

This repo ships a ready-made [Claude Code skill](skills/ensemble/SKILL.md) that handles the whole
orchestration. The easiest way to install it — **copy the following into Claude Code and send it:**

```
Install the "ensemble" skill from github.com/psufka/llm-ensemble: create the folder
~/.claude/skills/ensemble/ and download
https://raw.githubusercontent.com/psufka/llm-ensemble/main/skills/ensemble/SKILL.md
into it as SKILL.md. Then check whether the codex, agy, and grok CLIs are
installed and tell me which ones I still need to set up.
```

Restart Claude Code so it loads the new skill — then just say `ensemble <question>`.

**Prefer to install it manually?**

```bash
git clone https://github.com/psufka/llm-ensemble
cp -r llm-ensemble/skills/ensemble ~/.claude/skills/ensemble
```

The skill checks that the `codex`, `agy`, and `grok` CLIs are installed (it never installs
them) and skips any that are missing.

## Safe by default

These CLIs are coding *agents* — normally they can read, write, and run commands. The skill keeps them to
**answering only**: everything runs in a throwaway scratch dir (`mktemp -d`), Codex in a read-only sandbox,
Grok with its file/shell tools disabled, and a watchdog kills any tool that hangs. A normal ensemble run
can't touch your project, and one stuck model can't stall the batch.

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
- **Models stay current — and tell you which they are** — Codex and Grok ride their CLIs' rolling
  defaults; the skill runs `agy models` once per session to lock in the newest non-Flash Gemini Pro,
  and reports the exact model each tool is using on the first ensemble of a chat. Tracks new releases
  without re-checking on every call.

## Credit

Inspired by Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council).
