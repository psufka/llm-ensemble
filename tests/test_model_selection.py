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


class ClaudeModelSelectionTests(unittest.TestCase):
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


class GeminiModelSelectionTests(unittest.TestCase):
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


class GrokModelSelectionTests(unittest.TestCase):
    def test_default_model_line_parsed(self) -> None:
        self.assertEqual(run_ensemble.choose_grok_model(["Default model: grok-4-1030"]), "grok-4-1030")

    def test_starred_default_parsed(self) -> None:
        self.assertEqual(run_ensemble.choose_grok_model(["  * grok-4 (default)"]), "grok-4")

    def test_no_default_returns_empty(self) -> None:
        self.assertEqual(run_ensemble.choose_grok_model(["grok-4", "grok-3"]), "")


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


class OpenRouterScoringTests(unittest.TestCase):
    def test_context_contribution_is_capped(self) -> None:
        score, _ = select_openrouter_free_model.score_candidate("m", "m", 2_000_000, 0, False, False, "")
        self.assertEqual(score, 500.0)

    def test_reasoning_weight(self) -> None:
        with_reasoning, _ = select_openrouter_free_model.score_candidate("m", "m", 100_000, 0, True, False, "")
        without_reasoning, _ = select_openrouter_free_model.score_candidate("m", "m", 100_000, 0, False, False, "")
        self.assertEqual(with_reasoning - without_reasoning, 400.0)


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
