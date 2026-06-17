---
name: ensemble
description: Run a question through multiple AI CLIs at once (OpenAI Codex, Google Gemini, xAI Grok), compare their answers to your own, and return one synthesized answer. Use when the user says "ensemble [question]", asks for a cross-model second opinion, or wants to fact-check / stress-test a high-stakes decision, claim, or piece of writing. Requires the codex, gemini (or agy), and grok CLIs to be installed and authenticated.
---

# Ensemble

Run an important question through several frontier models at once, then synthesize a single answer that's better than any one model alone. You (Claude) orchestrate: answer first, fan the same question out to the other CLIs in parallel, compare, and merge.

## Prerequisites — required, not installed by this skill

This skill **assumes the other AI CLIs are already installed and authenticated.** It must never attempt to install them. Before running, verify what's available:

```bash
command -v codex agy gemini grok
```

- Use `agy` if present; otherwise fall back to `gemini`.
- If a CLI is missing, **skip that model** and note it in the output.
- If fewer than two external CLIs are available, tell the user the ensemble needs at least two and point them to the install steps in the repo README (`https://github.com/psufka/llm-ensemble`). Do not proceed with a single model and call it an ensemble.

## Steps

When the user says `ensemble [question]` (or asks for a cross-model take):

1. **Answer first.** Write your own best answer before calling anything. The point is to cross-check your judgment, not outsource it.

2. **Fan out in parallel.** Send the **same** prompt to each available CLI concurrently (run the commands in one batch, not sequentially). Run from a scratch dir (e.g. `/tmp`) so the agentic CLIs don't index the working folder:

   ```bash
   # OpenAI Codex
   codex exec -m gpt-5.5 -c model_reasoning_effort="xhigh" "QUESTION"

   # Google Gemini (Antigravity)
   agy --model "Gemini 3.1 Pro (High)" -p "QUESTION"
   # fallback if agy is absent:
   gemini --skip-trust -m gemini-3.1-pro-preview -p "QUESTION"

   # xAI Grok
   grok -p "QUESTION" --always-approve --disallowed-tools "search_replace,run_terminal_cmd"
   ```

   - Use the identical prompt for every model so answers are comparable.
   - If a CLI errors, proceed with the rest — two responding models is enough.
   - **Never use Flash-tier models.** `agy` defaults to Gemini Flash, so the `--model` flag is mandatory.
   - Model IDs drift; if a model 404s, check the tool's current best model and swap the ID.

3. **Compare.** Lay out where all models agree, where they diverge, and any blind spot only one caught. Note confidence.

4. **Synthesize.** Return **one** integrated answer — not a vote tally, not three pasted transcripts. Take the strongest reasoning from each, and explicitly flag any claim the models disagreed on so the user knows where to dig.

## When to use it

- Decisions with real stakes — career, strategy, money
- Fact-checking — if the models agree, a claim is more likely right; if they diverge, dig deeper
- Writing — parallel drafts surface angles one model won't
- Checking your own assumptions — different training biases triangulate blind spots

Skip it for trivial lookups; one model is fine there.
