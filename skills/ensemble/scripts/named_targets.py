"""Resolve user-named targets against the catalogs available on this machine."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass, replace
from typing import Any

import select_openrouter_free_model as router


LOCAL_PROVIDERS = ("agy", "grok", "codex")
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


class TargetError(ValueError):
    """A requested target could not be selected without another decision."""

    def __init__(self, message: str, target: Target | None = None) -> None:
        super().__init__(message)
        self.target = target


class PartialMatch(TargetError):
    """A shorter name matched catalog entries but cannot select this version."""


@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    label: str
    effort: str = ""
    supported_efforts: tuple[str, ...] = ()
    free: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.provider}:{self.model}"


def grok_models(lines: list[str]) -> tuple[str, list[str]]:
    default = ""
    available = []
    for line in lines:
        match = re.fullmatch(r"\s*(Default model:|[-*])\s+(\S+?)(\s+\(default\))?\s*", line, re.I)
        if match:
            model = match[2]
            if match[1].lower() == "default model:" or (match[3] and not default):
                default = model
            if model not in available:
                available.append(model)
    return default, available


def cli_output(command: list[str]) -> str:
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise TargetError((result.stderr or result.stdout or f"exit {result.returncode}").strip()[-350:])
    return result.stdout


def tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z]+|\d+", text.casefold()))


def trailing_effort(words: tuple[str, ...]) -> str:
    return words[-1] if words and words[-1] in EFFORTS else ""


def load_catalog(provider: str) -> list[Target]:
    if provider == "agy":
        data = json.loads(cli_output(["agy", "--output-format", "json", "models"]))
        if data.get("status") != "SUCCESS":
            raise TargetError("agy models did not succeed; check Antigravity sign-in")
        entries = data["command"]["data"]["models"]
        return [
            Target(provider, row["id"], row.get("label") or row["id"],
                   trailing_effort(tokens(row["id"])) or trailing_effort(tokens(row.get("label", ""))))
            for row in entries if isinstance(row, dict) and row.get("id")
        ]
    if provider == "codex":
        data = json.loads(cli_output(["codex", "debug", "models"]))
        entries = data["models"] if isinstance(data, dict) else data
        return [
            Target(provider, row["slug"], row.get("display_name") or row["slug"],
                   supported_efforts=tuple(level["effort"] for level in row.get("supported_reasoning_levels", [])))
            for row in entries if isinstance(row, dict) and row.get("slug") and row.get("visibility", "list") == "list"
        ]
    if provider == "grok":
        _, models = grok_models(cli_output(["grok", "models"]).splitlines())
        return [Target(provider, model, model) for model in models]
    request = urllib.request.Request(router.OPENROUTER_MODELS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=12) as response:
        entries = json.load(response)["data"]
    return [
        Target(provider, row["id"], row.get("name") or row["id"], free=is_free(row.get("pricing") or {}))
        for row in entries if isinstance(row, dict) and row.get("id") and router.has_text_output_from_api(row)
    ]


def is_free(pricing: dict[str, Any]) -> bool:
    return (router.decimal_zero(pricing.get("prompt")) and router.decimal_zero(pricing.get("completion"))
            and all(router.decimal_zero(price) for price in pricing.values()))


def split_target(request: str) -> tuple[str, str]:
    prefix, colon, rest = request.strip().partition(":")
    if colon and prefix.lower() in (*LOCAL_PROVIDERS, "openrouter"):
        return prefix.lower(), rest.strip()
    return "", request.strip()


def model_names(target: Target, strip_effort: bool = False) -> set[tuple[str, ...]]:
    names = set()
    for name in (target.model, target.model.split("/")[-1], target.label.split(": ")[-1]):
        words = tokens(name)
        if strip_effort and target.effort and trailing_effort(words) == target.effort:
            words = words[:-1]
        names.add(words)
        if words[:1] == ("claude",):
            names.add(words[1:])
    return names


def choose(name: str, candidates: list[Target], *, exact_only: bool = False) -> Target | None:
    """Match whole names first. Collapse only effort variants of the same advertised ID."""
    words = tokens(name)
    if not words:
        raise TargetError("Specify a model name after --target.")
    # "Fugu Ultra" and "GPT-5.1-Codex-Max" are complete catalog names.
    # Interpret an effort word as an override only after checking the full name.
    effort = "" if any(words in model_names(t) for t in candidates) else trailing_effort(words)
    if effort:
        words = words[:-1]
    ranks: dict[int, list[Target]] = {}
    for target in candidates:
        names = model_names(target) | model_names(target, strip_effort=True)
        if name.casefold() == target.model.casefold():
            rank = 3
        elif words in names:
            rank = 2
        elif words and any(words == form[i:i+len(words)] for form in names for i in range(len(form))):
            rank = 1
        else:
            continue
        ranks.setdefault(rank, []).append(target)
    if not ranks:
        return None
    rank = max(ranks)
    matches = ranks[rank]
    if rank == 1 and exact_only:
        return None
    groups: dict[tuple[str, tuple[str, ...]], list[Target]] = {}
    for target in matches:
        base = tokens(target.model)
        if target.provider == "agy" and target.effort and trailing_effort(base) == target.effort:
            base = base[:-1]
        groups.setdefault((target.provider, base), []).append(target)
    if len(groups) > 1 or (rank == 1 and any(word.isdigit() for word in words)):
        choices = ", ".join(t.qualified for t in matches[:16])
        error = PartialMatch if rank == 1 else TargetError
        raise error(f"Choose an exact model for {name!r}. Matches: {choices}")
    if effort:
        for target in matches:
            # Grok lists model IDs, with per-model effort validation performed at launch.
            grok_effort = target.provider == "grok" and effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max")
            if target.effort == effort or effort in target.supported_efforts or grok_effort:
                return replace(target, effort=effort)
        raise TargetError(f"Effort {effort!r} is unavailable for {name!r}. Choices: "
                          + ", ".join(t.qualified for t in matches))
    target = max(matches, key=lambda t: EFFORTS.index(t.effort) if t.effort in EFFORTS else -1)
    if target.supported_efforts:
        # The Codex catalog exposes effort separately from the selectable model ID.
        highest = next((level for level in reversed(EFFORTS) if level in target.supported_efforts), "")
        target = replace(target, effort=highest)
    return target


class Catalogs:
    """One snapshot per provider per run, including catalog failures."""

    def __init__(self) -> None:
        self.errors: dict[str, str] = {}
        self._models: dict[str, list[Target]] = {}

    def models(self, provider: str) -> list[Target]:
        if provider not in self._models:
            try:
                self._models[provider] = load_catalog(provider)
                if not self._models[provider]:
                    self.errors[provider] = "empty catalog"
            except Exception as exc:
                # A malformed or interrupted catalog must not discard other providers' answers.
                self._models[provider] = []
                self.errors[provider] = str(exc)
        return self._models[provider]

    def resolve(self, request: str, resolve_only: bool = False) -> Target:
        provider, name = split_target(request)
        providers = (provider,) if provider else LOCAL_PROVIDERS
        try:
            target = choose(name, [t for p in providers for t in self.models(p)])
        except PartialMatch:
            # A CLI listing 5.5 is not a route to version 5. Check the exact
            # catalog name before offering CLI alternatives for an unqualified request.
            if provider:
                raise
            target = choose(name, self.models("openrouter"), exact_only=True)
            if target is None:
                raise
        if not target and not provider:
            target = choose(name, self.models("openrouter"))
        if not target:
            searched = providers if provider else (*LOCAL_PROVIDERS, "openrouter")
            errors = "; ".join(f"{p}: {self.errors[p]}" for p in searched if p in self.errors)
            raise TargetError(f"No match for {request!r} in {', '.join(searched)}." + (f" {errors}" if errors else ""))
        if target.provider == "openrouter" and not resolve_only:
            if not target.free and provider != "openrouter":
                raise TargetError(f"Paid OpenRouter route requires your choice. To use it, request {target.qualified}.", target)
            if not os.environ.get("OPENROUTER_API_KEY"):
                raise TargetError(f"{target.qualified} requires OPENROUTER_API_KEY.", target)
        return target
