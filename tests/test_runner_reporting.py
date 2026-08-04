from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "ensemble" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import run_ensemble
import select_openrouter_free_model


class RunnerReportingTests(unittest.TestCase):
    def test_main_lists_agy_models_once_for_claude_and_gemini(self) -> None:
        model_lines = ["Claude Opus 4.6 (Thinking)", "Gemini 3.1 Pro (High)"]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "prompt.txt"
            prompt_path.write_text("test prompt", encoding="utf-8")
            args = argparse.Namespace(
                orchestrator="other",
                orchestrator_model="test-runtime",
                prompt_file=prompt_path,
                output_dir=temp_path / "output",
                timeout=10,
                agy_max_prompt_bytes=100_000,
                codex_model="",
                codex_effort="",
                grok_model="",
                keep_workdirs=False,
                resolve_only=False,
                skip_leg=None,
                only_leg=None,
            )
            with mock.patch.object(run_ensemble, "parse_args", return_value=args), mock.patch.object(
                run_ensemble,
                "command_exists",
                side_effect=lambda command: command == "agy",
            ), mock.patch.object(
                run_ensemble,
                "list_agy_models",
                return_value=(model_lines, "", False),
            ) as list_models, mock.patch.object(
                run_ensemble,
                "run_claude",
                return_value=run_ensemble.LegResult(leg="claude", family="claude", ok=True),
            ), mock.patch.object(
                run_ensemble,
                "run_gemini",
                return_value=run_ensemble.LegResult(leg="gemini", family="gemini", ok=True),
            ), mock.patch.object(
                run_ensemble,
                "run_openrouter",
                return_value=run_ensemble.skip_result("openrouter", "openrouter", "test skip"),
            ), mock.patch("builtins.print"):
                self.assertEqual(run_ensemble.main(), 0)

        list_models.assert_called_once()

    def test_openrouter_display_avoids_redundant_provider_suffix(self) -> None:
        self.assertEqual(
            run_ensemble.display_model("openrouter", "vendor/model-v2:free"),
            "vendor/model-v2 (free)",
        )

    def test_prompted_model_rows_preserve_retry_outcomes(self) -> None:
        leg = run_ensemble.LegResult(
            leg="openrouter",
            family="openrouter",
            model="vendor/model-b:free",
            models_prompted=["vendor/model-a:free", "vendor/model-b:free"],
            attempts=[
                {"phase": "query", "model": "vendor/model-a:free", "ok": False},
                {"phase": "query", "model": "vendor/model-b:free", "ok": True},
            ],
            ok=True,
        )

        rows = run_ensemble.prompted_model_rows(leg)

        self.assertEqual([row["attempt_ok"] for row in rows], [False, True])
        self.assertEqual(
            [row["display_model"] for row in rows],
            ["vendor/model-a (free)", "vendor/model-b (free)"],
        )

    def test_user_action_does_not_mask_full_ensemble(self) -> None:
        args = argparse.Namespace(orchestrator="codex", orchestrator_model="runtime-model", timeout=600)
        legs = [
            run_ensemble.LegResult(leg="claude", family="claude", ok=True),
            run_ensemble.LegResult(leg="grok", family="grok", ok=True),
            run_ensemble.LegResult(
                leg="gemini",
                family="gemini",
                requires_user_action=True,
                user_action="reauthenticate",
            ),
        ]
        manifest = run_ensemble.build_manifest(
            args,
            Path("/tmp/out"),
            Path("/tmp/prompt.txt"),
            Path("/tmp/external_prompt.txt"),
            legs,
        )

        self.assertEqual(manifest["mode"], "full")
        self.assertTrue(manifest["requires_user_action"])
        self.assertEqual(manifest["user_actions"], ["reauthenticate"])

    def test_auth_classification_avoids_bare_auth_substrings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "agy.log"
            log_path.write_text("authoritative model routing failed", encoding="utf-8")
            self.assertEqual(run_ensemble.classify_agy_log(log_path), "agy returned empty stdout")
            log_path.write_text("request failed: not authenticated", encoding="utf-8")
            self.assertEqual(run_ensemble.classify_agy_log(log_path), "agy auth issue")

    def test_openrouter_selection_exhaustion_uses_normal_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_cache = Path(temp_dir) / "missing-models.json"
            with self.assertRaises(RuntimeError):
                select_openrouter_free_model.select_candidates(cache_path=missing_cache, offline=True)

    def test_openrouter_selection_failure_stays_inside_its_leg(self) -> None:
        args = argparse.Namespace(
            no_openrouter_smoke=False,
            openrouter_attempts=3,
            openrouter_smoke_limit=6,
            openrouter_smoke_timeout=20,
            openrouter_temperature=0.2,
            openrouter_max_tokens=4096,
            openrouter_timeout=600,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            run_ensemble.os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "select_candidates",
            side_effect=RuntimeError("no free models"),
        ):
            result = run_ensemble.run_openrouter(Path(temp_dir), "prompt", args)

        self.assertFalse(result.ok)
        self.assertEqual(result.exit_code, "selection-error")
        self.assertIn("no free models", result.failure_reason)

    def test_openrouter_smoke_runs_concurrently_and_keeps_rank_order(self) -> None:
        candidates = [
            SimpleNamespace(model_id=f"vendor/model-{index}:free", name=f"Model {index}")
            for index in range(6)
        ]
        args = argparse.Namespace(
            no_openrouter_smoke=False,
            openrouter_attempts=2,
            openrouter_smoke_limit=6,
            openrouter_smoke_timeout=20,
        )
        with mock.patch.dict(run_ensemble.os.environ, {"OPENROUTER_API_KEY": "test-key"}), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "select_candidates",
            return_value=candidates,
        ), mock.patch.object(
            run_ensemble.select_openrouter_free_model,
            "smoke_model",
            side_effect=lambda candidate, api_key, timeout: candidate.model_id
            not in {"vendor/model-0:free", "vendor/model-2:free"},
        ) as smoke_model:
            selected, attempts = run_ensemble.openrouter_attempt_candidates(args)

        # All limit candidates are smoked concurrently; passing candidates are
        # preferred in rank order regardless of which smoke finished first.
        self.assertEqual([candidate.model_id for candidate in selected], [
            "vendor/model-1:free",
            "vendor/model-3:free",
        ])
        self.assertEqual(len(attempts), 6)
        self.assertEqual(smoke_model.call_count, 6)
        self.assertEqual(
            [attempt["passed"] for attempt in attempts],
            [False, True, False, True, True, True],
        )


if __name__ == "__main__":
    unittest.main()
