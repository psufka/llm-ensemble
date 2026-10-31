import contextlib
import http.client
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/ensemble/scripts"))
import named_targets as names
import openrouter_query
import run_ensemble as runner


class NameTests(unittest.TestCase):
    def test_version_and_effort_are_distinct(self):
        choices = [names.Target("agy", "claude-opus-" + version.replace(".", "-") + "-" + effort,
                                f"Claude Opus {version} ({effort})", effort)
                   for version in ("5.5", "5.50") for effort in ("low", "medium", "high")]
        self.assertEqual(names.choose("Opus 5.5", choices).model, "claude-opus-5-5-high")
        self.assertEqual(names.choose("OPUS 5.5 medium", choices).model, "claude-opus-5-5-medium")
        self.assertIsNone(names.choose("Opus 5.6", choices))
        with self.assertRaisesRegex(names.TargetError, "Choose an exact model"):
            names.choose("Opus", choices)
        with self.assertRaisesRegex(names.TargetError, "unavailable"):
            names.choose("Opus 5.5 xhigh", choices)

    def test_effort_words_in_model_names_are_preserved(self):
        options = [names.Target("openrouter", f"sakana/fugu-{tier}", f"Sakana: Fugu {tier}")
                   for tier in ("max", "ultra")]
        for name in ("Fugu Max", "sakana/fugu-max"):
            self.assertEqual(names.choose(name, options), options[0])

    def test_catalog_cache_and_exact_paid_route(self):
        local = names.Target("agy", "claude-opus-5-5-high", "Claude Opus 5.5 (High)", "high")
        paid = names.Target("openrouter", "anthropic/claude-opus-5", "Anthropic: Claude Opus 5")
        by_provider = {"agy": [local], "openrouter": [paid], "codex": [], "grok": []}
        cats = names.Catalogs()
        with mock.patch.object(names, "load_catalog", side_effect=by_provider.__getitem__) as load, \
                mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "fixture"}):
            self.assertEqual(cats.resolve("Opus 5.5"), local)
            self.assertNotIn(mock.call("openrouter"), load.call_args_list)
            with self.assertRaisesRegex(names.TargetError, "Paid OpenRouter route"):
                cats.resolve("Opus 5")
            self.assertEqual(cats.resolve("Opus 5", resolve_only=True), paid)
            self.assertEqual(cats.resolve("openrouter:anthropic/claude-opus-5"), paid)
            with self.assertRaisesRegex(names.TargetError, "Choose an exact model"):
                cats.resolve("agy:Opus 5")
            self.assertEqual(load.call_count, 4)

    def test_free_prices_require_complete_zero_pricing(self):
        self.assertTrue(names.is_free({"prompt": "0", "completion": "0.0", "request": 0}))
        for price in ({}, {"prompt": 0}, {"prompt": 0, "completion": 0, "request": 0.1}):
            self.assertFalse(names.is_free(price))
        response = io.BytesIO(b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}')
        with mock.patch.object(openrouter_query.urllib.request, "urlopen", return_value=response) as post:
            openrouter_query.query_openrouter("q", "vendor/free", api_key="fixture", free_only=True)
        body = json.loads(post.call_args.args[0].data)
        self.assertEqual(body["provider"]["max_price"], {"prompt": 0, "completion": 0, "request": 0})


class NamedWorkflowTests(unittest.TestCase):
    """Real argv, provider subprocesses and status files, with deterministic offline catalogs."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.prompt = self.root / "question.txt"
        self.prompt.write_text("Which version?", encoding="utf-8")
        self.output = self.root / "output"
        self.calls = self.root / "calls.jsonl"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        stub = """import json, os, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
if 'models' in args:
    if tool == 'agy':
        rows = [{'id':'claude-opus-5-5-'+tier, 'label':'Claude Opus 5.5 ('+tier+')'} for tier in ['low','medium','high']]
        print(json.dumps({'status':'SUCCESS', 'command':{'data':{'models':rows}}}))
    elif tool == 'codex':
        print(json.dumps({'models':[{'slug':'gpt-6-sol','display_name':'GPT-6 Sol','visibility':'list',
             'supported_reasoning_levels':[{'effort':'low'},{'effort':'high'}]}]}))
    else:
        print('Default model: grok-4.7\\n  * grok-4.7 (default)\\n  - grok-4.7-build-fast')
    sys.exit(0)
model = args[args.index('--model')+1]
with Path(os.environ['CALLS_FILE']).open('a') as f:
    print(json.dumps({'model':model,'args':args}),file=f)
if os.environ.get('FAIL_MODEL') == model:
    sys.exit(5)
print('answer from ' + model)
"""
        for name in ("agy", "codex", "grok"):
            exe = self.bin / name
            exe.write_text("#!"+sys.executable+"\n"+stub, encoding="utf-8")
            exe.chmod(0o700)
        env = mock.patch.dict(os.environ, {"PATH": str(self.bin), "CALLS_FILE": str(self.calls)})
        env.start()
        self.addCleanup(env.stop)
        scores = mock.patch.object(runner, "make_intelligence_catalog")
        scores.start().return_value.configure_mock(**{"lookup.return_value": None, "metadata.return_value": {}})
        self.addCleanup(scores.stop)

    def invoke(self, *args):
        argv = ["runner", "--orchestrator", "claude", "--prompt-file", str(self.prompt),
                "--output-dir", str(self.output), *args]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            code = runner.main()
        status = json.loads((self.output / "status.json").read_text())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return code, status, calls

    def test_single_same_family_with_sources(self):
        sources = self.root / "sources.txt"
        sources.write_text("https://example.test/ Evidence supplied by the host.", encoding="utf-8")
        code, status, calls = self.invoke("--target", "Opus 5.5", "--sources-file", str(sources))
        self.assertEqual((code, status["mode"], status["source_mode"]), (0, "single-model", "host-supplied"))
        self.assertEqual([c["model"] for c in calls], ["claude-opus-5-5-high"])
        self.assertIn("--sandbox", calls[0]["args"])
        self.assertIn("--disable-slash-commands", calls[0]["args"])
        self.assertIn(sources.read_text(), calls[0]["args"][-1])
        self.assertEqual([r["provider"] for r in status["models_prompted"]], ["agy"])
        self.assertEqual(status["blind_answers_dir"], "")

    def test_multiple_targets_with_shared_provider_and_duplicate_alias(self):
        code, status, calls = self.invoke("--target", "Opus 5.5", "--target", "Opus 5.5 medium",
                                          "--target", "Grok 4.7", "--target", "agy:claude-opus-5-5-high")
        self.assertEqual((code, status["mode"]), (0, "selected-models"))
        self.assertCountEqual([c["model"] for c in calls], ["claude-opus-5-5-high", "claude-opus-5-5-medium", "grok-4.7"])
        answers = [Path(leg["stdout_path"]) for leg in status["legs"]]
        self.assertEqual(len(set(answers)), 3)
        self.assertTrue(all(p.read_text().strip() == "answer from "+leg["model"] for p, leg in zip(answers, status["legs"])))
        self.assertEqual(len(json.loads((Path(status["blind_answers_dir"])/"mapping.json").read_text())), 3)

    def test_resolve_only_never_prompts(self):
        code, status, calls = self.invoke("--resolve-only", "--target", "codex:GPT-6 Sol low", "--target", "Grok 4.7")
        self.assertEqual((code, status["mode"], calls, status["models_prompted"]), (0, "resolve-only", [], []))
        self.assertEqual(status["legs"][0]["reasoning_effort"], "low")

    def test_codex_without_advertised_efforts_uses_its_default(self):
        model = names.Target("codex", "codex-test", "Codex Test")
        with mock.patch.object(names, "load_catalog", return_value=[model]):
            code, status, calls = self.invoke("--target", "codex:codex-test")
        self.assertEqual((code, status["mode"]), (0, "single-model"))
        self.assertNotIn('model_reasoning_effort=""', calls[0]["args"])
        self.assertIn("multi_agent", calls[0]["args"])

    def test_failed_target_keeps_peer_and_retries_only_same_model(self):
        with mock.patch.dict(os.environ, {"FAIL_MODEL": "grok-4.7"}):
            code, status, calls = self.invoke("--target", "agy:Opus 5.5", "--target", "grok:Grok 4.7")
        self.assertNotEqual(code, 0)
        self.assertEqual(status["mode"], "partial-targets")
        self.assertCountEqual([c["model"] for c in calls], ["claude-opus-5-5-high", "grok-4.7", "grok-4.7"])
        self.assertEqual([r["attempt_ok"] for r in status["models_prompted"]], [True, False, False])
        self.assertTrue(Path(status["legs"][0]["stdout_path"]).is_file())

    def test_broken_catalog_does_not_discard_success(self):
        with mock.patch.object(names.urllib.request, "urlopen", side_effect=http.client.IncompleteRead(b"")):
            code, status, calls = self.invoke("--target", "agy:Opus 5.5", "--target", "openrouter:missing/model")
        self.assertNotEqual(code, 0)
        self.assertEqual([c["model"] for c in calls], ["claude-opus-5-5-high"])
        self.assertEqual(status["mode"], "partial-targets")
        self.assertIn("IncompleteRead", status["legs"][1]["failure_reason"])

    def test_implicit_paid_run_does_not_query(self):
        paid = names.Target("openrouter", "vendor/paid", "Named Model")
        with mock.patch.object(names, "load_catalog", side_effect=lambda p: [paid] if p == "openrouter" else []), \
                mock.patch.object(openrouter_query, "query_openrouter") as query:
            code, status, calls = self.invoke("--target", "Named Model")
        query.assert_not_called()
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertTrue(status["requires_user_action"])
        self.assertIn("openrouter:vendor/paid", status["user_actions"][0])

    def test_automatic_free_openrouter_query_is_price_capped(self):
        model = names.Target("openrouter", "vendor/example:free", "Example", free=True)
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "fixture"}), \
                mock.patch.object(names, "load_catalog", side_effect=lambda p: [model] if p == "openrouter" else []), \
                mock.patch.object(runner.select_openrouter_free_model, "find_model", return_value=None), \
                mock.patch.object(openrouter_query, "query_openrouter", return_value=("answer", "stop")) as query:
            code, status, _ = self.invoke("--target", "Example")
        self.assertEqual((code, status["mode"]), (0, "single-model"))
        self.assertEqual(query.call_args.args[1], model.model)
        self.assertTrue(query.call_args.kwargs["free_only"])
        self.assertEqual(status["models_prompted"][0]["provider"], "openrouter")

    def test_nonempty_directory_keeps_permissions(self):
        self.output.mkdir()
        self.output.chmod(0o755)
        (self.output / "existing").touch()
        with self.assertRaisesRegex(SystemExit, "fresh --output-dir"):
            self.invoke("--target", "Opus 5.5")
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o755)

    def test_conflicting_roster_controls_rejected_before_discovery(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.invoke("--target", "Opus 5.5", "--only-leg", "gemini")
        self.assertFalse(self.output.exists())
