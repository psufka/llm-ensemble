#!/usr/bin/env python3
"""Select the best currently available free OpenRouter text model.

The script prefers live OpenRouter model metadata and falls back to OpenCode's
models cache. It prints a model id by default, or shell assignments with
--format shell.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models?sort=intelligence-high-to-low"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
SMOKE_MARKER = "OPENROUTER_FREE_MODEL_SMOKE_OK"

# OpenRouter vendor prefixes per ensemble model family, so the free-model
# wildcard can be kept independent of labs already answering in the ensemble.
FAMILY_VENDOR_PREFIXES = {
    "claude": ("anthropic/",),
    "codex": ("openai/",),
    "gemini": ("google/",),
    "grok": ("x-ai/", "xai/"),
}


def excluded_by_vendor(model_id: str, exclude_families: Iterable[str]) -> bool:
    lowered = model_id.lower()
    for family in exclude_families:
        prefixes = FAMILY_VENDOR_PREFIXES.get(family)
        if prefixes is None:
            # Entries ending in "/" are raw vendor prefixes (e.g. "moonshotai/"),
            # used to keep the free wildcard independent of a pinned model's lab.
            prefixes = (family.lower(),) if family.endswith("/") else ()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return True
    return False


@dataclass
class Candidate:
    model_id: str
    name: str
    context: int
    output: int
    reasoning: bool
    structured: bool
    release_date: str
    source: str
    score: float
    notes: str
    intelligence: float | None = None
    coding: float | None = None
    agentic: float | None = None
    intelligence_source: str = ""


def decimal_zero(value: Any) -> bool:
    if value is None:
        return False
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def has_text_output_from_api(model: dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    output_modalities = model.get("output_modalities")
    if isinstance(output_modalities, list):
        return "text" in [str(x).lower() for x in output_modalities]
    modality = str(architecture.get("modality") or model.get("modality") or "").lower()
    if "text" in modality and "image" not in modality:
        return True
    # Many OpenRouter text models omit explicit output_modalities.
    return bool(model.get("id")) and not re.search(r"(embedding|whisper|tts|image|audio|video)", model.get("id", ""), re.I)


def has_text_output_from_cache(model: dict[str, Any]) -> bool:
    modalities = model.get("modalities") or {}
    output = modalities.get("output") if isinstance(modalities, dict) else None
    if isinstance(output, list):
        return "text" in [str(x).lower() for x in output]
    return True


def excluded(model_id: str, name: str) -> bool:
    text = f"{model_id} {name}".lower()
    hard_excludes = [
        "embedding",
        "rerank",
        "whisper",
        "tts",
        "audio",
        "music",
        "lyria",
        "clip",
        "video",
        "moderation",
        "guard",
        "safety",
        "content-safety",
        "image",
    ]
    return any(term in text for term in hard_excludes)


def artificial_analysis_scores(model: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    benchmarks = model.get("benchmarks") or {}
    aa = benchmarks.get("artificial_analysis") or {}
    return (
        as_float(aa.get("intelligence_index")),
        as_float(aa.get("coding_index")),
        as_float(aa.get("agentic_index")),
    )


def release_score(release_date: str) -> float:
    if not release_date:
        return 0
    match = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", release_date)
    if not match:
        return 0
    year = int(match.group(1))
    month = int(match.group(2) or "1")
    day = int(match.group(3) or "1")
    try:
        delta = (date.today() - date(year, month, day)).days
    except ValueError:
        return 0
    return max(0, 250 - delta / 4)


def normalize_release_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return str(value)
    text = str(value)
    if re.fullmatch(r"\d{10}", text):
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return text
    return text


def size_pattern(size: str) -> str:
    return rf"(?<![\d.]){re.escape(size)}(?!\d)"


def size_score(model_id: str, name: str) -> float:
    text = f"{model_id} {name}".lower()
    score = 0.0
    for size, points in [
        ("1t", 350),
        ("550b", 320),
        ("480b", 285),
        ("405b", 260),
        ("120b", 190),
        ("80b", 140),
        ("70b", 115),
        ("32b", 55),
        ("30b", 45),
        ("20b", 25),
    ]:
        if re.search(size_pattern(size), text):
            score += points
            break
    if "ultra" in text:
        score += 150
    if "super" in text:
        score += 100
    if "coder" in text:
        score += 40
    if "router/free" in text:
        score -= 300
    if re.search(r"(^|[-_/ ])nano($|[-_/ ])", text):
        score -= 120
    if re.search(r"(^|[-_/ ])3b($|[-_/ ])", text):
        score -= 100
    if re.search(r"1\.2b", text):
        score -= 160
    return score


def score_candidate(
    model_id: str,
    name: str,
    context: int,
    output: int,
    reasoning: bool,
    structured: bool,
    release_date: str,
    intelligence: float | None = None,
) -> tuple[float, str]:
    score = 0.0
    # Context is capped at 500 points so a long-context weak model cannot
    # outrank a strong reasoner on window size alone.
    score += min(context, 1_000_000) / 2000
    score += min(output, 128_000) / 4000
    if reasoning:
        score += 400
    if structured:
        score += 80
    score += release_score(release_date)
    score += size_score(model_id, name)
    index_note = f" aa_intelligence={intelligence:g}" if intelligence is not None else " aa_intelligence=unavailable"
    notes = (
        f"context={context} output={output} reasoning={reasoning} structured={structured} "
        f"release={release_date or 'unknown'}{index_note}"
    )
    return score, notes


def candidate_rank(candidate: Candidate) -> tuple[bool, float, float]:
    """Rank by the live intelligence index, using heuristics only as a fallback/tiebreaker."""
    intelligence = candidate.intelligence if candidate.intelligence is not None else float("-inf")
    return candidate.intelligence is not None, intelligence, candidate.score


def from_openrouter_api(timeout: float = 10.0) -> list[Candidate]:
    req = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data", payload if isinstance(payload, list) else [])
    candidates: list[Candidate] = []
    for model in data:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id") or "")
        name = str(model.get("name") or model_id)
        pricing = model.get("pricing") or {}
        if not (decimal_zero(pricing.get("prompt")) and decimal_zero(pricing.get("completion"))):
            continue
        if excluded(model_id, name) or not has_text_output_from_api(model):
            continue
        context = as_int(model.get("context_length") or (model.get("top_provider") or {}).get("context_length"))
        if context <= 0:
            continue
        output = as_int((model.get("top_provider") or {}).get("max_completion_tokens") or model.get("max_completion_tokens"))
        supported = [str(x).lower() for x in model.get("supported_parameters", []) if isinstance(x, str)]
        reasoning = "reasoning" in supported or "include_reasoning" in supported
        structured = "response_format" in supported or "structured_outputs" in supported
        release_date = normalize_release_date(model.get("created") or model.get("release_date"))
        intelligence, coding, agentic = artificial_analysis_scores(model)
        score, notes = score_candidate(model_id, name, context, output, reasoning, structured, release_date, intelligence)
        candidates.append(
            Candidate(
                model_id,
                name,
                context,
                output,
                reasoning,
                structured,
                release_date,
                "openrouter_api",
                score,
                notes,
                intelligence,
                coding,
                agentic,
                "Artificial Analysis via OpenRouter" if intelligence is not None else "",
            )
        )
    return candidates


def from_opencode_cache(path: Path) -> list[Candidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    models = (((payload.get("openrouter") or {}).get("models")) or {})
    candidates: list[Candidate] = []
    for model_id, model in models.items():
        if not isinstance(model, dict):
            continue
        name = str(model.get("name") or model_id)
        cost = model.get("cost") or {}
        if not (decimal_zero(cost.get("input")) and decimal_zero(cost.get("output"))):
            continue
        if excluded(model_id, name) or not has_text_output_from_cache(model):
            continue
        limit = model.get("limit") or {}
        context = as_int(limit.get("context"))
        if context <= 0:
            continue
        output = as_int(limit.get("output"))
        reasoning = bool(model.get("reasoning"))
        structured = bool(model.get("structured_output"))
        release_date = str(model.get("release_date") or model.get("last_updated") or "")
        score, notes = score_candidate(model_id, name, context, output, reasoning, structured, release_date)
        candidates.append(Candidate(model_id, name, context, output, reasoning, structured, release_date, "opencode_cache", score, notes))
    return candidates


def select_candidates(
    cache_path: Path | None = None,
    offline: bool = False,
    exclude_families: Iterable[str] = (),
) -> list[Candidate]:
    exclude_families = tuple(exclude_families)

    def usable(candidates: list[Candidate]) -> list[Candidate]:
        kept = [c for c in candidates if not excluded_by_vendor(c.model_id, exclude_families)]
        return sorted(kept, key=candidate_rank, reverse=True)

    errors: list[str] = []
    if not offline:
        try:
            candidates = usable(from_openrouter_api())
            if candidates:
                return candidates
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"openrouter_api:{exc}")
    cache_path = cache_path or Path.home() / ".cache/opencode/models.json"
    try:
        candidates = usable(from_opencode_cache(cache_path))
        if candidates:
            return candidates
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"opencode_cache:{exc}")
    detail = f" (excluding families: {', '.join(exclude_families)})" if exclude_families else ""
    raise RuntimeError(f"No eligible free OpenRouter text models found{detail}. " + "; ".join(errors))


def find_model(model_id: str, cache_path: Path | None = None, timeout: float = 10.0) -> Candidate | None:
    """Look up metadata for an arbitrary OpenRouter model id, free or paid.

    Unlike select_candidates this applies no pricing or capability filters —
    it exists so the runner can clamp max_tokens for a user-pinned model.
    Returns None when the id is unknown or both metadata sources fail.
    """
    wanted = model_id.strip().lower()
    if not wanted:
        return None
    try:
        req = urllib.request.Request(OPENROUTER_MODELS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data", payload if isinstance(payload, list) else [])
        for model in data:
            if not isinstance(model, dict) or str(model.get("id") or "").lower() != wanted:
                continue
            name = str(model.get("name") or model_id)
            context = as_int(model.get("context_length") or (model.get("top_provider") or {}).get("context_length"))
            output = as_int((model.get("top_provider") or {}).get("max_completion_tokens") or model.get("max_completion_tokens"))
            supported = [str(x).lower() for x in model.get("supported_parameters", []) if isinstance(x, str)]
            reasoning = "reasoning" in supported or "include_reasoning" in supported
            structured = "response_format" in supported or "structured_outputs" in supported
            release_date = normalize_release_date(model.get("created") or model.get("release_date"))
            intelligence, coding, agentic = artificial_analysis_scores(model)
            return Candidate(
                model_id,
                name,
                context,
                output,
                reasoning,
                structured,
                release_date,
                "openrouter_api",
                0.0,
                "pinned lookup",
                intelligence,
                coding,
                agentic,
                "Artificial Analysis via OpenRouter" if intelligence is not None else "",
            )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass
    cache_path = cache_path or Path.home() / ".cache/opencode/models.json"
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        models = (((payload.get("openrouter") or {}).get("models")) or {})
        for cache_id, model in models.items():
            if str(cache_id).lower() != wanted or not isinstance(model, dict):
                continue
            name = str(model.get("name") or model_id)
            limit = model.get("limit") or {}
            context = as_int(limit.get("context"))
            output = as_int(limit.get("output"))
            reasoning = bool(model.get("reasoning"))
            structured = bool(model.get("structured_output"))
            release_date = str(model.get("release_date") or model.get("last_updated") or "")
            return Candidate(model_id, name, context, output, reasoning, structured, release_date, "opencode_cache", 0.0, "pinned lookup")
    except (OSError, json.JSONDecodeError):
        pass
    return None


def smoke_model(candidate: Candidate, api_key: str, timeout: float) -> bool:
    body = {
        "model": candidate.model_id,
        "messages": [
            {
                "role": "system",
                "content": "Follow the user's instruction exactly. Do not use tools.",
            },
            {"role": "user", "content": f"Reply exactly: {SMOKE_MARKER}"},
        ],
        "temperature": 0,
        "max_tokens": 64,
    }
    req = urllib.request.Request(
        OPENROUTER_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/psufka/llm-ensemble",
            "X-Title": "llm-ensemble",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    choices = payload.get("choices") or []
    if not choices:
        return False
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    return content == SMOKE_MARKER


def choose_candidate(candidates: list[Candidate], smoke: bool, smoke_limit: int, smoke_timeout: float) -> Candidate:
    if not smoke:
        return candidates[0]
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return candidates[0]
    for candidate in candidates[:smoke_limit]:
        if smoke_model(candidate, api_key, smoke_timeout):
            candidate.notes += " smoke=pass"
            candidate.score += 10_000
            return candidate
    candidates[0].notes += " smoke=no-pass-fallback"
    return candidates[0]


def print_candidate(candidate: Candidate, output_format: str) -> None:
    if output_format == "id":
        print(candidate.model_id)
    elif output_format == "shell":
        print(f"OPENROUTER_MODEL={shlex.quote(candidate.model_id)}")
        print(f"OPENROUTER_MODEL_NAME={shlex.quote(candidate.name)}")
        print(f"OPENROUTER_MODEL_INTELLIGENCE={shlex.quote('' if candidate.intelligence is None else str(candidate.intelligence))}")
        print(f"OPENROUTER_MODEL_REASON={shlex.quote(candidate.notes + ' source=' + candidate.source + ' score=' + str(round(candidate.score, 1)))}")
    elif output_format == "json":
        print(json.dumps(candidate.__dict__, indent=2, sort_keys=True))
    else:
        intelligence = "unavailable" if candidate.intelligence is None else f"{candidate.intelligence:g}"
        print(
            f"{candidate.model_id}\t{candidate.name}\t{candidate.notes}\t{candidate.source}"
            f"\taa_intelligence={intelligence}\theuristic_score={candidate.score:.1f}"
        )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["id", "shell", "json", "tsv"], default="id")
    parser.add_argument("--list", action="store_true", help="print ranked candidates instead of only the top model")
    parser.add_argument("--offline", action="store_true", help="skip live OpenRouter API and use OpenCode cache")
    parser.add_argument("--cache", type=Path, default=None, help="path to OpenCode models.json cache")
    parser.add_argument("--smoke", action="store_true", help="prefer the first high-ranked model that passes an exact-output API smoke test")
    parser.add_argument("--smoke-limit", type=int, default=6, help="number of ranked candidates to smoke-test")
    parser.add_argument("--smoke-timeout", type=float, default=20, help="seconds per smoke-test request")
    parser.add_argument(
        "--exclude-family",
        action="append",
        choices=sorted(FAMILY_VENDOR_PREFIXES),
        help="exclude free models from this ensemble family's vendor (repeatable)",
    )
    args = parser.parse_args(argv)

    try:
        candidates = select_candidates(cache_path=args.cache, offline=args.offline, exclude_families=args.exclude_family or ())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.list:
        for candidate in candidates[:20]:
            print_candidate(candidate, "tsv")
    else:
        print_candidate(choose_candidate(candidates, args.smoke, args.smoke_limit, args.smoke_timeout), args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
