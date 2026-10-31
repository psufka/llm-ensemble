from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "ensemble" / "scripts"


class ArgonWorkflowTests(unittest.TestCase):
    """Exercise the real runner and subprocess dispatch with a local agy fixture."""

    def run_fixture(self, *, argon_available: bool, only_agy: bool) -> tuple[dict, list, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            catalog = "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\nclaude-opus-5-5-high\tClaude Opus 5.5 (High)\n"
            if argon_available:
                catalog += "gemini-4-argon-medium\tGemini 4 Argon (Medium)\ngemini-4-argon-high\tGemini 4 Argon (High)\n"
            (root / "catalog.txt").write_text(catalog, encoding="utf-8")
            (root / "prompt.txt").write_text("Reply with exactly ARGON_SMOKE_OK.", encoding="utf-8")
            fixture = f"#!{sys.executable}\n" + textwrap.dedent("""
                import json
                import os
                import sys
                from pathlib import Path

                root = Path(os.environ["ENSEMBLE_TEST_ROOT"])
                if Path(sys.argv[0]).name == "agy-models-15s" or sys.argv[1:] == ["models"]:
                    print((root / "catalog.txt").read_text(), end="")
                else:
                    with (root / "calls.jsonl").open("a") as log:
                        log.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
                    model = sys.argv[sys.argv.index("--model") + 1]
                    if model not in ("gemini-4-argon-high", "claude-opus-5-5-high"):
                        raise SystemExit("unexpected model")
                    print("ARGON_SMOKE_OK" if model == "gemini-4-argon-high" else "CLAUDE_SMOKE_OK")
            """)
            for executable in ("agy", "agy-models-15s"):
                stub = bin_dir / executable
                stub.write_text(fixture, encoding="utf-8")
                stub.chmod(0o700)
            # Only benchmark metadata is stubbed in the runner; argparse,
            # selection, subprocess launch, answer files, and manifest are real.
            driver = (
                f"import sys; sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
                "import run_ensemble as r; "
                "from types import SimpleNamespace; "
                "r.make_intelligence_catalog = lambda: SimpleNamespace("
                "lookup=lambda *args: None, metadata=lambda: {}); "
                "raise SystemExit(r.main())"
            )
            command = [
                sys.executable, "-c", driver,
                "--orchestrator", "codex",
                "--orchestrator-model", "test-runtime",
                "--orchestrator-effort", "test",
                "--prompt-file", str(root / "prompt.txt"),
                "--output-dir", str(root / "output"),
                "--timeout", "10",
            ]
            if only_agy:
                command += ["--only-leg", "agy"]
            env = os.environ.copy()
            env["PATH"] = str(bin_dir)
            env["ENSEMBLE_TEST_ROOT"] = str(root)
            env.pop("OPENROUTER_API_KEY", None)
            completed = subprocess.run(command, env=env, text=True, capture_output=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            status = json.loads((root / "output/status.json").read_text())
            calls_file = root / "calls.jsonl"
            calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
            answer = (root / "output/gemini.out").read_text() if (root / "output/gemini.out").exists() else ""
            if calls:
                self.assertEqual(calls[0]["cwd"], str((root / "output").resolve()))
                self.assertIn("--sandbox", calls[0]["args"])
            return status, calls, answer

    def test_only_agy_uses_exact_argon_id_and_returns_its_answer(self) -> None:
        status, calls, answer = self.run_fixture(argon_available=True, only_agy=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(answer.strip(), "ARGON_SMOKE_OK")
        self.assertEqual(status["valid_external_count"], 1)
        models = [row["model"] for row in status["models_prompted"] if row["leg"] != "orchestrator"]
        self.assertEqual(models, ["gemini-4-argon-high"])
        self.assertFalse(status["requires_user_action"])

    def test_default_ensemble_runs_claude_and_argon_through_agy(self) -> None:
        status, calls, answer = self.run_fixture(argon_available=True, only_agy=False)
        self.assertEqual(len(calls), 2)
        called_models = sorted(call["args"][call["args"].index("--model") + 1] for call in calls)
        self.assertEqual(called_models, ["claude-opus-5-5-high", "gemini-4-argon-high"])
        self.assertEqual(answer.strip(), "ARGON_SMOKE_OK")
        claude = next(leg for leg in status["legs"] if leg["leg"] == "claude")
        self.assertTrue(claude["ok"])
        self.assertEqual(claude["models_prompted"], ["claude-opus-5-5-high"])
        self.assertEqual(status["mode"], "full")
        self.assertEqual(status["valid_external_count"], 2)

    def test_missing_argon_still_allows_the_separate_claude_leg(self) -> None:
        status, calls, answer = self.run_fixture(argon_available=False, only_agy=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"][calls[0]["args"].index("--model") + 1], "claude-opus-5-5-high")
        self.assertEqual(answer, "")
        self.assertEqual(status["mode"], "degraded-second-opinion")
        self.assertEqual(status["valid_external_count"], 1)
        self.assertTrue(status["requires_user_action"])

    def test_missing_argon_reports_action_and_sends_no_prompt(self) -> None:
        status, calls, answer = self.run_fixture(argon_available=False, only_agy=True)
        self.assertEqual(calls, [])
        self.assertEqual(answer, "")
        self.assertEqual(status["mode"], "needs-user-action")
        self.assertEqual(status["valid_external_count"], 0)
        self.assertTrue(status["requires_user_action"])
        self.assertTrue(any("Argon" in action for action in status["user_actions"]))


if __name__ == "__main__":
    unittest.main()
