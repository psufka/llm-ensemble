#!/usr/bin/env python3
"""Resolve live Artificial Analysis intelligence scores for runtime model names.

OpenRouter exposes Artificial Analysis benchmark fields for its active catalog.
Artificial Analysis model pages are used as a narrow fallback for models that a
local CLI still offers after OpenRouter has stopped publishing their score.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models?sort=intelligence-high-to-low"
OPENROUTER_MODELS_DOCS_URL = "https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties"
ARTIFICIAL_ANALYSIS_MODEL_URL = "https://artificialanalysis.ai/models/{slug}"

_MODEL_MODIFIERS = {
    "adaptive",
    "batch",
    "free",
    "high",
    "latest",
    "low",
    "max",
    "medium",
    "preview",
    "reasoning",
    "thinking",
    "xhigh",
}
_PROVIDER_LABELS = {
    "anthropic",
    "google",
    "openai",
    "spacexai",
    "x-ai",
    "xai",
}


@dataclass(frozen=True)
class IntelligenceScore:
    intelligence: float
    coding: float | None = None
    agentic: float | None = None
    source: str = "Artificial Analysis via OpenRouter"
    source_url: str = OPENROUTER_MODELS_DOCS_URL
    retrieved_at: str = ""
    matched_model: str = ""
    estimated: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _model_parts(raw_model: str) -> list[str]:
    parts = [part.strip() for part in raw_model.split("\t") if part.strip()]
    return parts or [raw_model.strip()]


def canonical_model_key(raw_model: str) -> str:
    """Normalize provider IDs, display names, effort labels, and version separators."""
    text = raw_model.strip().lower()
    if not text:
        return ""
    if "/" in text:
        text = text.split("/", 1)[1]
    elif ":" in text:
        prefix, remainder = text.split(":", 1)
        if prefix.strip() in _PROVIDER_LABELS:
            text = remainder
    text = re.sub(r":(?:batch|free)$", "", text)
    tokens = re.findall(r"[a-z]+|\d+", text)
    if tokens and tokens[0] in {"anthropic", "google", "openai", "spacexai", "xai"}:
        tokens = tokens[1:]
    tokens = [token for token in tokens if token not in _MODEL_MODIFIERS]
    if tokens and tokens[-1] == "t" and any(token in tokens for token in ("claude", "opus", "sonnet", "haiku")):
        tokens = tokens[:-1]
    return "-".join(tokens)


def canonical_model_keys(raw_model: str) -> list[str]:
    keys: list[str] = []
    for part in _model_parts(raw_model):
        key = canonical_model_key(part)
        if key and key not in keys:
            keys.append(key)
    return keys


class IntelligenceCatalog:
    """Thread-safe, process-local cache of live intelligence benchmark data."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: dict[str, IntelligenceScore] = {}
        self._page_cache: dict[str, IntelligenceScore | None] = {}
        self._errors: list[str] = []
        self._retrieved_at = ""

    def _load_openrouter(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._retrieved_at = utc_now()
        request = urllib.request.Request(
            OPENROUTER_MODELS_URL,
            headers={"Accept": "application/json", "User-Agent": "llm-ensemble/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self._errors.append(f"OpenRouter intelligence lookup failed: {exc}")
            return
        data = payload.get("data", payload if isinstance(payload, list) else [])
        for model in data:
            if not isinstance(model, dict):
                continue
            benchmarks = model.get("benchmarks") or {}
            aa = benchmarks.get("artificial_analysis") or {}
            intelligence = as_float(aa.get("intelligence_index"))
            if intelligence is None:
                continue
            model_id = str(model.get("id") or "")
            model_name = str(model.get("name") or "")
            score = IntelligenceScore(
                intelligence=intelligence,
                coding=as_float(aa.get("coding_index")),
                agentic=as_float(aa.get("agentic_index")),
                retrieved_at=self._retrieved_at,
                matched_model=model_id or model_name,
            )
            for alias in (model_id, model_name):
                for key in canonical_model_keys(alias):
                    existing = self._entries.get(key)
                    if existing is None or score.intelligence > existing.intelligence:
                        self._entries[key] = score

    @staticmethod
    def _page_slugs(key: str) -> list[str]:
        # The public page fallback is intentionally narrow. OpenRouter handles
        # active models; this catches Claude models retained by agy after their
        # benchmark row disappears from OpenRouter's active catalog.
        if not key.startswith("claude-"):
            return []
        return [f"{key}-adaptive", key]

    def _load_artificial_analysis_page(self, key: str) -> IntelligenceScore | None:
        if key in self._page_cache:
            return self._page_cache[key]
        for slug in self._page_slugs(key):
            url = ARTIFICIAL_ANALYSIS_MODEL_URL.format(slug=slug)
            request = urllib.request.Request(url, headers={"User-Agent": "llm-ensemble/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    html = response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                self._errors.append(f"Artificial Analysis lookup failed for {slug}: HTTP {exc.code}")
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._errors.append(f"Artificial Analysis lookup failed for {slug}: {exc}")
                break
            match = re.search(
                r"scores?\s+(\d+(?:\.\d+)?)\s+on the Artificial Analysis Intelligence Index",
                html,
                re.I,
            )
            if not match:
                continue
            score = IntelligenceScore(
                intelligence=float(match.group(1)),
                source="Artificial Analysis",
                source_url=url,
                retrieved_at=utc_now(),
                matched_model=slug,
                estimated=True,
                note="Runtime reasoning configuration matched to the model's adaptive/max-effort benchmark page.",
            )
            self._page_cache[key] = score
            return score
        self._page_cache[key] = None
        return None

    def lookup(self, model: str, family: str = "") -> IntelligenceScore | None:
        del family  # Reserved for provider-specific disambiguation as catalogs evolve.
        with self._lock:
            self._load_openrouter()
            keys = canonical_model_keys(model)
            for key in keys:
                if key in self._entries:
                    return self._entries[key]
            for key in keys:
                score = self._load_artificial_analysis_page(key)
                if score is not None:
                    return score
        return None

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            self._load_openrouter()
            return {
                "metric": "Artificial Analysis Intelligence Index",
                "primary_source": "OpenRouter model benchmarks",
                "primary_source_url": OPENROUTER_MODELS_DOCS_URL,
                "fallback_source": "Artificial Analysis model pages",
                "retrieved_at": self._retrieved_at,
                "indexed_model_count": len(self._entries),
                "errors": list(self._errors),
            }
