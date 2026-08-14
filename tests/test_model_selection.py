from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "ensemble" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import openrouter_query
import run_ensemble
import select_openrouter_free_model


def static_catalog(scores: dict[str, float]) -> mock.Mock:
    catalog = mock.Mock()

    def lookup(model: str, family: str = "") -> object:
        del family
        lowered = model.lower()
        for marker, value in scores.items():
            if marker in lowered:
                return run_ensemble.model_intelligence.IntelligenceScore(value)
        return None

    catalog.lookup.side_effect = lookup
    return catalog


class ClaudeModelSelectionTests(unittest.TestCase):
    def test_live_index_can_rank_sonnet_above_opus(self) -> None:
        lines = [
            "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)",
            "claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)",
        ]
        catalog = static_catalog({"sonnet-4-6": 48.4, "opus-4-6": 45.0})
        self.assertEqual(run_ensemble.choose_claude_model(lines, catalog), "claude-sonnet-4-6")

    def test_mythos_and_fable_outrank_opus(self) -> None:
        lines = ["Claude Opus 4.6 (Thinking)", "Claude Fable 5 (Thinking)", "Claude Mythos 5"]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "Claude Mythos 5")
        lines = ["Claude Opus 4.6 (Thinking)", "Claude Fable 5"]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "Claude Fable 5")

    def test_new_tier_names_recognized_without_claude_prefix(self) -> None:
        lines = ["Fable 5", "Claude Opus 4.6 (Thinking)"]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "Fable 5")

    def test_thinking_preferred_within_same_tier_and_version(self) -> None:
        lines = ["Claude Opus 4.6", "Claude Opus 4.6 (Thinking)"]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "Claude Opus 4.6 (Thinking)")

    def test_version_parse_handles_prefixed_names(self) -> None:
        self.assertEqual(run_ensemble.parse_claude_version("Claude Fable 5 (Thinking)"), (5,))
        self.assertEqual(run_ensemble.parse_claude_version("Fable 5.1"), (5, 1))
        self.assertEqual(run_ensemble.parse_claude_version("Claude Opus 4.6"), (4, 6))

    def test_slug_format_agy_listing(self) -> None:
        # agy switched to slug names (observed 2026-08-04): hyphenated versions,
        # tier as a suffix, no "Claude"-style display names guaranteed.
        self.assertEqual(run_ensemble.parse_claude_version("claude-opus-4-6-thinking"), (4, 6))
        lines = ["claude-sonnet-4-6", "claude-opus-4-6-thinking"]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "claude-opus-4-6-thinking")
        lines = ["claude-opus-4-5-thinking", "claude-opus-4-6-thinking"]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "claude-opus-4-6-thinking")

    def test_tab_separated_id_and_display_columns(self) -> None:
        # Real agy output observed 2026-08-08: "model-id<TAB>Display Name".
        # Only the id column is a valid --model value, but the display column
        # may carry information missing from the slug (here: Thinking).
        lines = [
            "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)",
            "claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)",
        ]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "claude-opus-4-6-thinking")
        # Thinking-only-in-display still beats a non-thinking sibling slug.
        lines = [
            "claude-opus-4-6\tClaude Opus 4.6",
            "claude-opus-4-6-t\tClaude Opus 4.6 (Thinking)",
        ]
        self.assertEqual(run_ensemble.choose_claude_model(lines), "claude-opus-4-6-t")


class GeminiModelSelectionTests(unittest.TestCase):
    def test_live_index_can_rank_flash_above_pro(self) -> None:
        lines = [
            "gemini-3.7-flash-high\tGemini 3.7 Flash (High)",
            "gemini-3.1-pro-high\tGemini 3.1 Pro (High)",
        ]
        catalog = static_catalog({"3.7-flash": 56.0, "3.1-pro": 47.7})
        self.assertEqual(run_ensemble.choose_gemini_model(lines, catalog), "gemini-3.7-flash-high")

    def test_ultra_outranks_pro_regardless_of_version(self) -> None:
        lines = ["Gemini 3.1 Pro (High)", "Gemini 3 Ultra (Medium)"]
        self.assertEqual(run_ensemble.choose_gemini_model(lines), "Gemini 3 Ultra (Medium)")

    def test_high_tier_preferred_within_same_model(self) -> None:
        lines = ["Gemini 3.1 Pro (Low)", "Gemini 3.1 Pro (High)"]
        self.assertEqual(run_ensemble.choose_gemini_model(lines), "Gemini 3.1 Pro (High)")

    def test_tier_parsed_from_any_parenthesized_group(self) -> None:
        lines = ["Gemini 3.1 Pro (Preview) (High)", "Gemini 3.1 Pro (Low)"]
        self.assertEqual(run_ensemble.choose_gemini_model(lines), "Gemini 3.1 Pro (Preview) (High)")

    def test_slug_format_agy_listing(self) -> None:
        # Real agy output observed 2026-08-04; the old parser saw no tier and
        # alphabetical fallback picked "low" over "high".
        lines = [
            "gemini-3.6-flash-high",
            "gemini-3.6-flash-medium",
            "gemini-3.1-pro-high",
            "gemini-3.1-pro-low",
        ]
        self.assertEqual(run_ensemble.choose_gemini_model(lines), "gemini-3.1-pro-high")
        self.assertEqual(run_ensemble.parse_gemini_version("gemini-3.1-pro-high"), (3, 1))
        self.assertEqual(run_ensemble.parse_model_tier("gemini-3.1-pro-high"), 3)
        self.assertEqual(run_ensemble.parse_model_tier("Gemini 3.1 Pro (High)"), 3)

    def test_tab_separated_id_and_display_columns(self) -> None:
        # Real agy output observed 2026-08-08: "model-id<TAB>Display Name".
        # Passing the whole line as --model made agy exit 1 and killed the leg.
        lines = [
            "Fetching available models...",
            "gemini-3.6-flash-high\tGemini 3.6 Flash (High)",
            "gemini-3.1-pro-high\tGemini 3.1 Pro (High)",
            "gemini-3.1-pro-low\tGemini 3.1 Pro (Low)",
        ]
        self.assertEqual(run_ensemble.choose_gemini_model(lines), "gemini-3.1-pro-high")
        self.assertEqual(run_ensemble.agy_model_id("gemini-3.1-pro-high\tGemini 3.1 Pro (High)"), "gemini-3.1-pro-high")
        self.assertEqual(run_ensemble.agy_model_id("Gemini 3.1 Pro (High)"), "Gemini 3.1 Pro (High)")


class GrokModelSelectionTests(unittest.TestCase):
    def test_default_model_line_parsed(self) -> None:
        self.assertEqual(run_ensemble.choose_grok_model(["Default model: grok-4-1030"]), "grok-4-1030")

    def test_starred_default_parsed(self) -> None:
        self.assertEqual(run_ensemble.choose_grok_model(["  * grok-4 (default)"]), "grok-4")

    def test_no_default_returns_empty(self) -> None:
        self.assertEqual(run_ensemble.choose_grok_model(["grok-4", "grok-3"]), "")

    def test_live_index_ranks_all_available_models(self) -> None:
        lines = ["Default model: grok-4.5", "  * grok-4.5 (default)", "  - grok-4.6"]
        catalog = static_catalog({"grok-4.5": 50.0, "grok-4.6": 60.9})
        self.assertEqual(run_ensemble.choose_grok_model(lines, catalog), "grok-4.6")


class CodexResolutionTests(unittest.TestCase):
    def test_effort_resolution_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                'model = "gpt-test"\nmodel_reasoning_effort = "max"\n\n[section]\nmodel_reasoning_effort = "low"\n',
                encoding="utf-8",
            )
            with mock.patch.dict(run_ensemble.os.environ, {"CODEX_HOME": temp_dir}, clear=True):
                self.assertEqual(run_ensemble.select_codex_model(""), ("gpt-test", ""))
                self.assertEqual(run_ensemble.select_codex_effort(""), "max")
                self.assertEqual(run_ensemble.select_codex_effort("medium"), "medium")
            with mock.patch.dict(
                run_ensemble.os.environ,
                {"CODEX_HOME": temp_dir, "ENSEMBLE_CODEX_EFFORT": "high"},
                clear=True,
            ):
                self.assertEqual(run_ensemble.select_codex_effort(""), "high")

    def test_effort_defaults_to_xhigh_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(run_ensemble.os.environ, {"CODEX_HOME": temp_dir}, clear=True):
                self.assertEqual(run_ensemble.select_codex_effort(""), "xhigh")

    def test_codex_orchestrator_effort_prefers_explicit_runtime_value(self) -> None:
        args = argparse.Namespace(
            orchestrator="codex",
            orchestrator_effort="max",
            codex_effort="medium",
        )

        self.assertEqual(run_ensemble.select_orchestrator_effort(args), "max")

    def test_codex_orchestrator_effort_falls_back_to_codex_resolution(self) -> None:
        args = argparse.Namespace(orchestrator="codex", codex_effort="high")

        self.assertEqual(run_ensemble.select_orchestrator_effort(args), "high")

    def test_non_codex_orchestrator_has_no_reasoning_effort_label(self) -> None:
        args = argparse.Namespace(orchestrator="claude", orchestrator_effort="max")

        self.assertEqual(run_ensemble.select_orchestrator_effort(args), "")


class OpenRouterScoringTests(unittest.TestCase):
    def test_flash_name_is_not_excluded_without_a_capability_reason(self) -> None:
        self.assertFalse(select_openrouter_free_model.excluded("vendor/new-flash:free", "New Flash"))

    def test_context_contribution_is_capped(self) -> None:
        score, _ = select_openrouter_free_model.score_candidate("m", "m", 2_000_000, 0, False, False, "")
        self.assertEqual(score, 500.0)

    def test_reasoning_weight(self) -> None:
        with_reasoning, _ = select_openrouter_free_model.score_candidate("m", "m", 100_000, 0, True, False, "")
        without_reasoning, _ = select_openrouter_free_model.score_candidate("m", "m", 100_000, 0, False, False, "")
        self.assertEqual(with_reasoning - without_reasoning, 400.0)

    def test_intelligence_index_dominates_tier_name_and_heuristics(self) -> None:
        flash = select_openrouter_free_model.Candidate(
            "vendor/flash:free", "Flash", 32_000, 1_000, False, False, "", "test", 10.0, "", 56.0
        )
        pro = select_openrouter_free_model.Candidate(
            "vendor/pro:free", "Pro", 1_000_000, 128_000, True, True, "", "test", 5_000.0, "", 47.7
        )
        ranked = sorted([pro, flash], key=select_openrouter_free_model.candidate_rank, reverse=True)
        self.assertEqual(ranked[0].model_id, "vendor/flash:free")


class OpenRouterTruncationTests(unittest.TestCase):
    def test_extract_content_returns_finish_reason(self) -> None:
        payload = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
        self.assertEqual(openrouter_query.extract_content(payload), ("hi", "stop"))

    def test_empty_content_at_length_is_retryable_with_reason(self) -> None:
        payload = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        with self.assertRaises(openrouter_query.OpenRouterError) as ctx:
            openrouter_query.extract_content(payload)
        self.assertTrue(ctx.exception.retryable)
        self.assertIn("finish_reason=length", str(ctx.exception))

    def test_run_openrouter_flags_truncation_and_clamps_max_tokens(self) -> None:
        candidate = SimpleNamespace(model_id="vendor/model:free", name="Model", output=1000)
        args = argparse.Namespace(
            no_openrouter_smoke=True,
            openrouter_attempts=3,
            openrouter_smoke_limit=6,
            openrouter_smoke_timeout=20,
            openrouter_temperature=0.2,
            openrouter_max_tokens=16_384,
            openrouter_timeout=600,
            resolve_only=False,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "select_candidates",
            return_value=[candidate],
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
            return_value=("partial answer", "length"),
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter(Path(temp_dir), "prompt", args)

        self.assertTrue(result.ok)
        self.assertTrue(result.truncated)
        query_attempt = [attempt for attempt in result.attempts if attempt.get("phase") == "query"][0]
        self.assertTrue(query_attempt["truncated"])
        self.assertEqual(query_attempt["max_tokens"], 1000)
        self.assertEqual(query.call_args.kwargs["max_tokens"], 1000)

    def test_run_openrouter_resolve_only_announces_without_prompting(self) -> None:
        candidate = SimpleNamespace(model_id="vendor/model:free", name="Model", output=0)
        args = argparse.Namespace(
            no_openrouter_smoke=True,
            openrouter_attempts=3,
            openrouter_smoke_limit=6,
            openrouter_smoke_timeout=20,
            openrouter_temperature=0.2,
            openrouter_max_tokens=16_384,
            openrouter_timeout=600,
            resolve_only=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "select_candidates",
            return_value=[candidate],
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter(Path(temp_dir), "", args)

        query.assert_not_called()
        self.assertTrue(result.skipped)
        self.assertEqual(result.exit_code, "resolve-only")
        self.assertEqual(result.model, "vendor/model:free")
        self.assertEqual(result.models_prompted, [])


class PinnedOpenRouterTests(unittest.TestCase):
    def _args(self, **overrides: object) -> argparse.Namespace:
        base: dict[str, object] = dict(
            openrouter_model="moonshotai/kimi-k3",
            openrouter_swap=False,
            openrouter_temperature=0.2,
            openrouter_max_tokens=16_384,
            openrouter_timeout=600,
            resolve_only=False,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_pinned_leg_queries_named_model_and_clamps_max_tokens(self) -> None:
        candidate = SimpleNamespace(model_id="moonshotai/kimi-k3", name="Kimi K3", output=1000)
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "find_model",
            return_value=candidate,
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
            return_value=("answer", "stop"),
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter_pinned(Path(temp_dir), "prompt", self._args())

        self.assertTrue(result.ok)
        self.assertEqual(result.leg, "openrouter-pinned")
        self.assertEqual(result.family, "openrouter-pinned")
        self.assertEqual(result.model, "moonshotai/kimi-k3")
        self.assertEqual(query.call_args.args[1], "moonshotai/kimi-k3")
        self.assertEqual(query.call_args.kwargs["max_tokens"], 1000)
        lookup = [attempt for attempt in result.attempts if attempt.get("phase") == "lookup"][0]
        self.assertTrue(lookup["found"])
        self.assertEqual(lookup["max_tokens"], 1000)

    def test_pinned_lookup_failure_uses_unclamped_max_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "find_model",
            return_value=None,
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
            return_value=("answer", "stop"),
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter_pinned(Path(temp_dir), "prompt", self._args())

        self.assertTrue(result.ok)
        self.assertEqual(query.call_args.kwargs["max_tokens"], 16_384)
        lookup = [attempt for attempt in result.attempts if attempt.get("phase") == "lookup"][0]
        self.assertFalse(lookup["found"])

    def test_pinned_retryable_error_retries_same_model_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "find_model",
            return_value=None,
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
            side_effect=[
                openrouter_query.OpenRouterError("rate limit", retryable=True),
                ("answer", "stop"),
            ],
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter_pinned(Path(temp_dir), "prompt", self._args())

        self.assertTrue(result.ok)
        self.assertEqual(query.call_count, 2)
        self.assertEqual(result.models_prompted, ["moonshotai/kimi-k3", "moonshotai/kimi-k3"])

    def test_pinned_non_retryable_error_does_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "find_model",
            return_value=None,
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
            side_effect=openrouter_query.OpenRouterError("invalid model", retryable=False),
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter_pinned(Path(temp_dir), "prompt", self._args())

        self.assertFalse(result.ok)
        self.assertEqual(query.call_count, 1)
        self.assertIn("invalid model", result.failure_reason)

    def test_pinned_resolve_only_announces_without_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.openrouter_query,
            "query_openrouter",
        ) as query, mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter_pinned(Path(temp_dir), "", self._args(resolve_only=True))

        query.assert_not_called()
        self.assertTrue(result.skipped)
        self.assertEqual(result.exit_code, "resolve-only")
        self.assertEqual(result.model, "moonshotai/kimi-k3")

    def test_pinned_skips_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {},
            clear=True,
        ), mock.patch("builtins.print"):
            result = run_ensemble.run_openrouter_pinned(Path(temp_dir), "prompt", self._args())

        self.assertTrue(result.skipped)
        self.assertEqual(result.skip_reason, "OPENROUTER_API_KEY is not set")

    def test_display_model_pinned_label(self) -> None:
        self.assertEqual(
            run_ensemble.display_model("openrouter-pinned", "moonshotai/kimi-k3"),
            "moonshotai/kimi-k3 (openrouter pinned)",
        )
        # The pinned label is literal — no :free stripping; the pin is the point.
        self.assertEqual(
            run_ensemble.display_model("openrouter-pinned", "vendor/model:free"),
            "vendor/model:free (openrouter pinned)",
        )
        self.assertEqual(
            run_ensemble.display_model("openrouter", "vendor/model:free"),
            "vendor/model (free)",
        )


class FindModelTests(unittest.TestCase):
    def _cache(self, path: Path) -> None:
        cache = {
            "openrouter": {
                "models": {
                    "moonshotai/kimi-k3": {
                        "name": "Kimi K3",
                        "cost": {"input": 1.5, "output": 6},
                        "limit": {"context": 256_000, "output": 8_192},
                        "reasoning": True,
                    }
                }
            }
        }
        path.write_text(json.dumps(cache), encoding="utf-8")

    def test_find_model_uses_cache_without_free_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models.json"
            self._cache(cache_path)
            with mock.patch.object(
                select_openrouter_free_model.urllib.request,
                "urlopen",
                side_effect=select_openrouter_free_model.urllib.error.URLError("offline"),
            ):
                candidate = select_openrouter_free_model.find_model("moonshotai/kimi-k3", cache_path=cache_path)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.model_id, "moonshotai/kimi-k3")
        self.assertEqual(candidate.output, 8_192)
        self.assertTrue(candidate.reasoning)

    def test_find_model_unknown_id_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models.json"
            self._cache(cache_path)
            with mock.patch.object(
                select_openrouter_free_model.urllib.request,
                "urlopen",
                side_effect=select_openrouter_free_model.urllib.error.URLError("offline"),
            ):
                candidate = select_openrouter_free_model.find_model("vendor/unknown-model", cache_path=cache_path)

        self.assertIsNone(candidate)


class VendorExclusionTests(unittest.TestCase):
    def _cache(self, path: Path) -> None:
        cache = {
            "openrouter": {
                "models": {
                    "google/gemma-9-27b": {
                        "name": "Gemma",
                        "cost": {"input": 0, "output": 0},
                        "limit": {"context": 128_000, "output": 8_000},
                    },
                    "nvidia/nemotron-test-70b": {
                        "name": "Nemotron",
                        "cost": {"input": 0, "output": 0},
                        "limit": {"context": 128_000, "output": 8_000},
                    },
                }
            }
        }
        path.write_text(json.dumps(cache), encoding="utf-8")

    def test_excluded_by_vendor(self) -> None:
        self.assertTrue(select_openrouter_free_model.excluded_by_vendor("google/gemma-9-27b", ["gemini"]))
        self.assertTrue(select_openrouter_free_model.excluded_by_vendor("openai/gpt-oss-120b", ["codex"]))
        self.assertTrue(select_openrouter_free_model.excluded_by_vendor("x-ai/grok-4-fast", ["grok"]))
        self.assertFalse(select_openrouter_free_model.excluded_by_vendor("nvidia/nemotron-test-70b", ["gemini", "codex", "claude", "grok"]))
        self.assertFalse(select_openrouter_free_model.excluded_by_vendor("google/gemma-9-27b", []))

    def test_raw_vendor_prefix_excluded(self) -> None:
        # Prefixes ending in "/" pass straight through — how the runner keeps
        # the free wildcard away from a pinned model's lab.
        self.assertTrue(select_openrouter_free_model.excluded_by_vendor("moonshotai/kimi-k3:free", ["moonshotai/"]))
        self.assertFalse(select_openrouter_free_model.excluded_by_vendor("nvidia/nemotron-test-70b", ["moonshotai/"]))
        # Unknown non-prefix entries are ignored rather than matching anything.
        self.assertFalse(select_openrouter_free_model.excluded_by_vendor("nvidia/nemotron-test-70b", ["openrouter-pinned"]))

    def test_select_candidates_filters_ensemble_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models.json"
            self._cache(cache_path)
            unfiltered = select_openrouter_free_model.select_candidates(cache_path=cache_path, offline=True)
            self.assertEqual(len(unfiltered), 2)
            filtered = select_openrouter_free_model.select_candidates(
                cache_path=cache_path, offline=True, exclude_families=["claude", "codex", "gemini", "grok"]
            )
            self.assertEqual([c.model_id for c in filtered], ["nvidia/nemotron-test-70b"])

    def test_exhaustive_exclusion_raises_with_family_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "models.json"
            cache = {
                "openrouter": {
                    "models": {
                        "google/gemma-9-27b": {
                            "name": "Gemma",
                            "cost": {"input": 0, "output": 0},
                            "limit": {"context": 128_000, "output": 8_000},
                        }
                    }
                }
            }
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                select_openrouter_free_model.select_candidates(
                    cache_path=cache_path, offline=True, exclude_families=["gemini"]
                )
            self.assertIn("gemini", str(ctx.exception))


class CliRetryTests(unittest.TestCase):
    def test_generic_failure_retried_once(self) -> None:
        calls = {"n": 0}

        def run_once() -> run_ensemble.LegResult:
            calls["n"] += 1
            if calls["n"] == 1:
                return run_ensemble.LegResult(
                    leg="codex", family="codex", model="m", exit_code=1, failure_reason="exit code 1"
                )
            return run_ensemble.LegResult(leg="codex", family="codex", model="m", ok=True, exit_code=0)

        with mock.patch("builtins.print"):
            result = run_ensemble.run_leg_with_retry(run_once)

        self.assertEqual(calls["n"], 2)
        self.assertTrue(result.ok)
        cli_attempts = [attempt for attempt in result.attempts if attempt.get("phase") == "cli"]
        self.assertEqual([attempt["attempt"] for attempt in cli_attempts], [1, 2])
        self.assertTrue(cli_attempts[1]["ok"])

    def test_auth_and_timeout_failures_not_retried(self) -> None:
        for result in [
            run_ensemble.LegResult(
                leg="codex", family="codex", exit_code=1,
                failure_reason="codex credentials need refresh", requires_user_action=True,
            ),
            run_ensemble.LegResult(leg="grok", family="grok", exit_code="timeout", failure_reason="timed out after 600s"),
            run_ensemble.LegResult(leg="gemini", family="gemini", exit_code=1, failure_reason="agy quota or rate limit"),
            run_ensemble.LegResult(leg="grok", family="grok", exit_code=0, failure_reason="grok sandbox could not be applied"),
        ]:
            calls = {"n": 0}

            def run_once(result=result) -> run_ensemble.LegResult:
                calls["n"] += 1
                return result

            with mock.patch("builtins.print"):
                run_ensemble.run_leg_with_retry(run_once)
            self.assertEqual(calls["n"], 1, msg=result.failure_reason)

    def test_success_not_retried(self) -> None:
        calls = {"n": 0}

        def run_once() -> run_ensemble.LegResult:
            calls["n"] += 1
            return run_ensemble.LegResult(leg="codex", family="codex", ok=True, exit_code=0)

        with mock.patch("builtins.print"):
            result = run_ensemble.run_leg_with_retry(run_once)
        self.assertEqual(calls["n"], 1)
        self.assertTrue(result.ok)


class BlindAnswersTests(unittest.TestCase):
    def test_writes_shuffled_answers_with_separate_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "codex.out").write_text("answer A", encoding="utf-8")
            (temp_path / "grok.out").write_text("answer B", encoding="utf-8")
            legs = [
                run_ensemble.LegResult(leg="codex", family="codex", model="gpt-x", ok=True, stdout_path=str(temp_path / "codex.out")),
                run_ensemble.LegResult(leg="grok", family="grok", model="grok-x", ok=True, stdout_path=str(temp_path / "grok.out")),
                run_ensemble.LegResult(leg="gemini", family="gemini", ok=False, failure_reason="failed"),
            ]
            answers_dir = run_ensemble.write_blind_answers(legs, temp_path)

            self.assertTrue(answers_dir.endswith("answers"))
            answer_files = sorted(Path(answers_dir).glob("answer-*.txt"))
            self.assertEqual(len(answer_files), 2)
            contents = {path.read_text(encoding="utf-8") for path in answer_files}
            self.assertEqual(contents, {"answer A", "answer B"})
            mapping = json.loads((Path(answers_dir) / "mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(mapping), ["answer-1.txt", "answer-2.txt"])
            self.assertEqual({entry["leg"] for entry in mapping.values()}, {"codex", "grok"})

    def test_no_valid_answers_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legs = [run_ensemble.LegResult(leg="codex", family="codex", ok=False)]
            self.assertEqual(run_ensemble.write_blind_answers(legs, Path(temp_dir)), "")
            self.assertFalse((Path(temp_dir) / "answers").exists())


class AuthClassificationTests(unittest.TestCase):
    def test_codex_login_failure_sets_user_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stderr_path = Path(temp_dir) / "codex.err"
            stderr_path.write_text("error: not logged in — run codex login\n", encoding="utf-8")
            result = run_ensemble.LegResult(
                leg="codex",
                family="codex",
                stderr_path=str(stderr_path),
                exit_code=1,
                failure_reason="exit code 1",
            )
            classified = run_ensemble.classify_cli_auth_failure(
                result, run_ensemble.CODEX_AUTH_TERMS, run_ensemble.CODEX_AUTH_ACTION
            )
        self.assertTrue(classified.requires_user_action)
        self.assertEqual(classified.user_action, run_ensemble.CODEX_AUTH_ACTION)

    def test_ordinary_failure_not_classified_as_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stderr_path = Path(temp_dir) / "grok.err"
            stderr_path.write_text("model overloaded, try again later\n", encoding="utf-8")
            result = run_ensemble.LegResult(
                leg="grok",
                family="grok",
                stderr_path=str(stderr_path),
                exit_code=1,
                failure_reason="exit code 1",
            )
            classified = run_ensemble.classify_cli_auth_failure(
                result, run_ensemble.GROK_AUTH_TERMS, run_ensemble.GROK_AUTH_ACTION
            )
        self.assertFalse(classified.requires_user_action)

    def test_successful_leg_never_reclassified(self) -> None:
        result = run_ensemble.LegResult(leg="codex", family="codex", ok=True)
        classified = run_ensemble.classify_cli_auth_failure(
            result, run_ensemble.CODEX_AUTH_TERMS, run_ensemble.CODEX_AUTH_ACTION
        )
        self.assertFalse(classified.requires_user_action)


if __name__ == "__main__":
    unittest.main()
