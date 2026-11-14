from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "ensemble" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import run_ensemble
import sensitive_scan as scan


# Test-only values; token prefixes are split so secret scanners do not flag this file.
VISA = "4111 1111 1111 1111"
MASTERCARD = "5555-5555-5555-4444"
AMEX = "3782 822463 10005"
SSN = "123-45-6789"
ROUTING = "021000021"
IBAN = "DE89 3704 0044 0532 0130 00"
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
GITHUB_TOKEN = "gh" + "p_" + "a1B2c3D4e5F6" * 3
OPENAI_KEY = "sk" + "-proj-" + "a1B2c3D4e5F6g7H8i9J0"
ANTHROPIC_KEY = "sk" + "-ant-api03-" + "a1B2c3D4e5F6g7H8i9J0"
SLACK_TOKEN = "xox" + "b-1234567890-abcdefghij"
GOOGLE_KEY = "AI" + "za" + "SyA1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVP"
PEM = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\nabcdEFGH1234abcdEFGH1234\n-----END " + "PRIVATE KEY-----"

EVERYDAY_BRIEF = """\
Call me at 612-555-0147 or (651) 555-0199, or +1 952 555 0123 after 5pm.
Meeting moved to 2026-11-13T10:15:30Z; the invoice is due 11/30/2026 and was sent 20261105.
Spreadsheet 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms has the numbers.
Task id 8123456789012 and order #1234567, Amazon order 114-1234567-1234567, timestamp 1731500000000.
Paid with the Visa ending in 4417 (account number ending in 4417), about $1,234,567.89 total.
Zip 55401-1234, build 2026.11.13.1, version 3.10.12, uuid 123e4567-e89b-12d3-a456-426614174000.
Password reset email arrived; the password: required field was empty. PIN pad is broken. Pin: ok
"""


class FindTests(unittest.TestCase):
    def kinds(self, text: str) -> list[str]:
        return [finding.kind for finding in scan.find_sensitive(text)]

    def test_card_numbers_need_luhn_and_a_known_issuer(self) -> None:
        for number in (VISA, "4111111111111111", MASTERCARD, AMEX, "3056 930902 5904", "6011 1111 1111 1117"):
            self.assertEqual(self.kinds(f"card {number} on file"), ["card"], number)
        self.assertEqual(self.kinds("card 4111 1111 1111 1112"), [])  # fails Luhn
        self.assertEqual(self.kinds("id 1731500000000"), [])  # no issuer prefix
        self.assertEqual(self.kinds("card 4111 1111 1111 1111 5 apples"), ["card"])
        self.assertEqual(self.kinds("ref 4111-1111-1111-1111-9999"), [])  # glued to a longer ID

    def test_ssn_formatted_unformatted_and_ranges(self) -> None:
        self.assertEqual(self.kinds(f"SSN {SSN}."), ["ssn"])
        self.assertEqual(self.kinds(f"my number is {SSN}"), ["ssn"])
        self.assertEqual(self.kinds("social security number is 123456789"), ["ssn"])
        self.assertEqual(self.kinds("ssn: 123456789"), ["ssn"])
        self.assertEqual(self.kinds("order 123456789"), [])  # no keyword
        for impossible in ("000-12-3456", "666-12-3456", "900-12-3456", "123-00-4567", "123-45-0000"):
            self.assertEqual(self.kinds(f"ssn {impossible}"), [], impossible)
        self.assertEqual(self.kinds("ssn 000123456"), [])

    def test_routing_needs_checksum_and_keyword(self) -> None:
        self.assertEqual(self.kinds(f"Routing number: {ROUTING}"), ["routing"])
        self.assertEqual(self.kinds(f"ABA {ROUTING}"), ["routing"])
        self.assertEqual(self.kinds(f"wire to {ROUTING}"), [])  # no keyword
        self.assertEqual(self.kinds("routing 123456789"), [])  # fails ABA checksum

    def test_account_numbers_need_a_keyword(self) -> None:
        for text in ("Account number: 12345678", "acct #55512345", "account # 9876543210", "Acct. no. 123456789012",
                     "my checking account 4455667788", "account number is 123-456-789"):
            self.assertEqual(self.kinds(text), ["account"], text)
        self.assertEqual(self.kinds("number 12345678"), [])
        self.assertEqual(self.kinds("account number 12345"), [])  # too short
        self.assertEqual(self.kinds("account number 12345678901234567890"), [])  # too long
        self.assertEqual(self.kinds("account number 20261113"), [])  # a date
        self.assertEqual(self.kinds("Account: 612-555-1234"), [])  # a phone number

    def test_dollar_amounts_after_an_account_keyword_are_not_accounts(self) -> None:
        for text in ("savings account has $125000 in it", "brokerage account: $ 1250000",
                     "checking account balance 125000.50"):
            self.assertEqual(self.kinds(text), [], text)
        self.assertEqual(self.kinds("savings account number 125000789"), ["account"])

    def test_iban_needs_mod97_and_country_length(self) -> None:
        self.assertEqual(self.kinds(f"IBAN {IBAN}"), ["iban"])
        self.assertEqual(self.kinds("GB82WEST12345698765432"), ["iban"])
        self.assertEqual(self.kinds("DE89 3704 0044 0532 0130 01"), [])  # bad check digits
        self.assertEqual(self.kinds("DE89 3704 0044 0532 0130"), [])  # too short

    def test_credentials(self) -> None:
        for text in ("password: Hunter2xyz", 'PASSWORD = "correct1 horse"', "DB_PASSWORD=s3cr3tvalue", 'pwd: \'abc-123\'',
                     "passcode: 482913", '{"password": "Sup3rS3cret!"}', "PIN 4821", "PIN: 4821", "my pin is 482913",
                     f"key {OPENAI_KEY}", f"key {ANTHROPIC_KEY}", f"token {GITHUB_TOKEN}", f"{SLACK_TOKEN}",
                     f"aws {AWS_KEY}", f"google {GOOGLE_KEY}", f"Authorization: Bearer {JWT}", f"key\n{PEM}\nend"):
            self.assertEqual(self.kinds(text), ["credential"], text)
        self.assertEqual(self.kinds("github_pat_" + "a1B2c3D4e5" * 6), ["credential"])

    def test_credential_false_positives(self) -> None:
        for text in ("the password: required", "Password: [see vault]", "password: ********", "password: <your password>",
                     "password: ${DB_PASS}", "Password reset link", "password: https://example.com/reset",
                     "password: password", "passwords: none", "pin: ok", "PIN pad", "risk-adjusted-return-calculations",
                     "bearer of long-standing-trustworthy-reputation", "task-1234567890123456789012",
                     "password: [REDACTED:credential]"):
            self.assertEqual(self.kinds(text), [], text)

    def test_everyday_brief_has_no_findings(self) -> None:
        self.assertEqual(scan.find_sensitive(EVERYDAY_BRIEF), [])

    def test_overlaps_keep_the_higher_priority_kind(self) -> None:
        findings = scan.find_sensitive(f"Account number: {VISA}")
        self.assertEqual([finding.kind for finding in findings], ["card"])
        findings = scan.find_sensitive(f"password: {VISA}")
        self.assertEqual([finding.kind for finding in findings], ["credential"])


class MaskTests(unittest.TestCase):
    def test_mask_replaces_values_and_keeps_labels(self) -> None:
        text = f"Visa {VISA}, SSN {SSN}, routing {ROUTING}, account number: 12345678, {IBAN}, password: Hunter2xyz"
        masked, findings = scan.mask_sensitive(text)
        self.assertEqual(
            masked,
            "Visa [REDACTED:card], SSN [REDACTED:ssn], routing [REDACTED:routing], "
            "account number: [REDACTED:account], [REDACTED:iban], password: [REDACTED:credential]",
        )
        self.assertEqual(len(findings), 6)
        self.assertEqual(scan.find_sensitive(masked), [])

    def test_mask_removes_whole_pem_block_and_leaves_other_text(self) -> None:
        masked, _ = scan.mask_sensitive(f"before\n{PEM}\nafter")
        self.assertEqual(masked, "before\n[REDACTED:credential]\nafter")

    def test_mask_leaves_clean_text_unchanged(self) -> None:
        self.assertEqual(scan.mask_sensitive(EVERYDAY_BRIEF)[0], EVERYDAY_BRIEF)

    def test_summary_has_counts_and_masked_previews_only(self) -> None:
        findings = scan.find_sensitive(f"{VISA} and {MASTERCARD}; password: Hunter2xyz; account number: 12345678")
        summary = scan.summarize(findings)
        self.assertEqual(summary, [
            {"kind": "card", "count": 2, "previews": ["****1111", "****4444"]},
            {"kind": "account", "count": 1, "previews": ["****"]},
            {"kind": "credential", "count": 1, "previews": ["password"]},
        ])
        self.assertNotIn("Hunter2xyz", json.dumps(summary))


class ScreenOutgoingTests(unittest.TestCase):
    def screen(self, mode: str, prompt: str, sources: str = "") -> tuple[str, str, dict, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            prompt, sources, report = run_ensemble.screen_outgoing(mode, prompt, sources)
        return prompt, sources, report, out.getvalue(), err.getvalue()

    def test_redact_masks_prompt_and_sources_and_reports_without_raw_values(self) -> None:
        prompt, sources, report, out, err = self.screen("redact", f"pay with {VISA}", f"statement account number: 12345678")
        self.assertEqual(prompt, "pay with [REDACTED:card]")
        self.assertEqual(sources, "statement account number: [REDACTED:account]")
        self.assertEqual(report["action"], "masked")
        self.assertEqual([row["kind"] for row in report["findings"]], ["card", "account"])
        self.assertEqual(err.count("\n"), 1)
        self.assertIn("1 card (****1111)", err)
        self.assertIn("SENSITIVE_EVENT=", out)
        for raw in ("4111", "12345678"):
            self.assertNotIn(raw, out + err + json.dumps(report))

    def test_allow_sends_unchanged_but_warns(self) -> None:
        prompt, _, report, out, err = self.screen("allow", f"pay with {VISA}")
        self.assertEqual(prompt, f"pay with {VISA}")
        self.assertEqual(report["action"], "sent unmasked")
        self.assertIn("sent unmasked", err)
        self.assertNotIn("4111", out + err)

    def test_block_exits_nonzero_and_warns(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            run_ensemble.screen_outgoing("block", f"pay with {VISA}", "")
        self.assertEqual(raised.exception.code, run_ensemble.SENSITIVE_BLOCKED_EXIT)
        self.assertIn("nothing was sent", err.getvalue())
        self.assertNotIn("4111", out.getvalue() + err.getvalue())

    def test_clean_prompt_is_silent(self) -> None:
        prompt, _, report, out, err = self.screen("redact", EVERYDAY_BRIEF)
        self.assertEqual(prompt, EVERYDAY_BRIEF)
        self.assertEqual((out, err, report["action"], report["findings"]), ("", "", "none", []))


class ParseArgsTests(unittest.TestCase):
    def parse(self, argv: list[str], env: dict[str, str] | None = None) -> argparse.Namespace:
        environ = {key: value for key, value in os.environ.items() if key != "ENSEMBLE_SENSITIVE"}
        environ.update(env or {})
        with mock.patch.object(sys, "argv", ["run_ensemble.py", "--orchestrator", "other", *argv]), mock.patch.dict(
            os.environ, environ, clear=True
        ):
            return run_ensemble.parse_args()

    def test_default_is_redact_and_env_and_flag_override(self) -> None:
        self.assertEqual(self.parse(["--prompt-file", "p.txt"]).sensitive, "redact")
        self.assertEqual(self.parse(["--prompt-file", "p.txt"], {"ENSEMBLE_SENSITIVE": "block"}).sensitive, "block")
        args = self.parse(["--prompt-file", "p.txt", "--sensitive", "allow"], {"ENSEMBLE_SENSITIVE": "block"})
        self.assertEqual(args.sensitive, "allow")

    def test_bad_env_value_is_an_error_but_not_for_resolve_only(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse(["--prompt-file", "p.txt"], {"ENSEMBLE_SENSITIVE": "off"})
        self.assertIsNone(self.parse(["--resolve-only"], {"ENSEMBLE_SENSITIVE": "off"}).sensitive)


class EmptyIntelligenceCatalog:
    def lookup(self, model: str, family: str = "") -> None:
        del model, family
        return None

    def metadata(self) -> dict[str, object]:
        return {"metric": "Artificial Analysis Intelligence Index", "errors": []}


class RunnerIntegrationTests(unittest.TestCase):
    def run_main(self, prompt: str, mode: str | None, *, resolve_only: bool = False) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            output_dir = temp_path / "output"
            args = argparse.Namespace(
                orchestrator="other", orchestrator_model="test-runtime", prompt_file=prompt_path,
                output_dir=output_dir, timeout=10, agy_max_prompt_bytes=100_000, codex_model="", codex_effort="",
                grok_model="", keep_workdirs=False, resolve_only=resolve_only, skip_leg=None, only_leg=None,
                openrouter_model="vendor/pinned", sensitive=mode,
            )
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(run_ensemble, "parse_args", return_value=args), mock.patch.object(
                run_ensemble, "make_intelligence_catalog", return_value=EmptyIntelligenceCatalog()
            ), mock.patch.object(
                run_ensemble, "command_exists", side_effect=lambda command: command == "agy"
            ), mock.patch.object(
                run_ensemble, "list_agy_models", return_value=(["claude-opus-5-5-high", "gemini-4-argon-high"], "", False)
            ), mock.patch.object(
                run_ensemble, "run_claude", return_value=run_ensemble.LegResult(leg="claude", family="claude", ok=True)
            ) as claude_leg, mock.patch.object(
                run_ensemble, "run_gemini", return_value=run_ensemble.LegResult(leg="gemini", family="gemini", ok=True)
            ) as gemini_leg, mock.patch.object(
                run_ensemble, "run_openrouter", return_value=run_ensemble.skip_result("openrouter", "openrouter", "skip")
            ) as free_leg, mock.patch.object(
                run_ensemble, "run_openrouter_pinned", return_value=run_ensemble.skip_result("openrouter-pinned", "x", "skip")
            ) as pinned_leg, mock.patch.object(
                run_ensemble, "screen_outgoing", wraps=run_ensemble.screen_outgoing
            ) as screen, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = run_ensemble.main()
                except SystemExit as exc:
                    code = exc.code
            files = {path.name: path.read_text(encoding="utf-8") for path in output_dir.glob("*") if path.is_file()}
            return {
                "code": code,
                "files": files,
                "output_exists": output_dir.exists(),
                "stdout": out.getvalue(),
                "stderr": err.getvalue(),
                "sent": {
                    "claude": [call.args[1] for call in claude_leg.call_args_list],
                    "gemini": [call.args[1] for call in gemini_leg.call_args_list],
                    "openrouter": [call.args[1] for call in free_leg.call_args_list],
                    "pinned": [call.args[1] for call in pinned_leg.call_args_list],
                },
                "screen_calls": screen.call_count,
            }

    def test_redact_masks_every_leg_every_saved_file_and_all_output(self) -> None:
        result = self.run_main(f"Is it safe to pay with {VISA}? password: Hunter2xyz", "redact")
        self.assertEqual(result["code"], 0)
        sent = [prompt for prompts in result["sent"].values() for prompt in prompts]
        self.assertEqual(len(sent), 4)  # claude, gemini, free OpenRouter, pinned OpenRouter
        for prompt in sent:
            self.assertIn("[REDACTED:card]", prompt)
            self.assertIn("password: [REDACTED:credential]", prompt)
        everything = "\n".join(sent) + result["stdout"] + result["stderr"] + "\n".join(result["files"].values())
        for raw in ("4111", "Hunter2xyz"):
            self.assertNotIn(raw, everything)
        self.assertIn("[REDACTED:card]", result["files"]["prompt.txt"])
        self.assertIn("[REDACTED:card]", result["files"]["external_prompt.txt"])
        status = json.loads(result["files"]["status.json"])
        self.assertEqual(status["sensitive"]["mode"], "redact")
        self.assertEqual(status["sensitive"]["action"], "masked")
        self.assertEqual(status["sensitive"]["findings"][0], {"kind": "card", "count": 1, "previews": ["****1111"]})
        self.assertEqual(result["stderr"].count("WARNING"), 1)
        self.assertIn("SENSITIVE_EVENT=", result["stdout"])

    def test_default_mode_is_redact(self) -> None:
        result = self.run_main(f"card {VISA}", None)
        self.assertNotIn("4111", result["files"]["external_prompt.txt"])

    def test_allow_sends_raw_and_records_masked_findings(self) -> None:
        result = self.run_main(f"card {VISA}", "allow")
        self.assertIn(VISA, result["sent"]["claude"][0])
        self.assertIn("sent unmasked", result["stderr"])
        status = json.loads(result["files"]["status.json"])
        self.assertEqual(status["sensitive"]["action"], "sent unmasked")
        self.assertNotIn("4111", result["stdout"] + result["stderr"] + result["files"]["status.json"])

    def test_block_exits_before_any_file_or_model(self) -> None:
        result = self.run_main(f"card {VISA}", "block")
        self.assertEqual(result["code"], run_ensemble.SENSITIVE_BLOCKED_EXIT)
        self.assertFalse(result["output_exists"])
        self.assertEqual(sum(len(prompts) for prompts in result["sent"].values()), 0)
        self.assertNotIn("4111", result["stdout"] + result["stderr"])

    def test_clean_prompt_is_unchanged_and_silent(self) -> None:
        result = self.run_main(EVERYDAY_BRIEF, "redact")
        self.assertEqual(result["stderr"], "")
        self.assertIn(EVERYDAY_BRIEF, result["sent"]["claude"][0])
        self.assertEqual(json.loads(result["files"]["status.json"])["sensitive"]["findings"], [])

    def test_resolve_only_skips_the_check(self) -> None:
        result = self.run_main(f"card {VISA}", "block", resolve_only=True)
        self.assertEqual(result["screen_calls"], 0)
        self.assertEqual(result["stderr"], "")
        self.assertNotIn("sensitive", json.loads(result["files"]["status.json"]))

    def test_sources_file_is_screened_for_named_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources = Path(temp_dir) / "sources.txt"
            sources.write_text(f"excerpt: account number: 12345678 and {IBAN}", encoding="utf-8")
            args = argparse.Namespace(
                orchestrator="other", orchestrator_model="m", prompt_file=Path(temp_dir) / "p.txt",
                output_dir=Path(temp_dir) / "out", timeout=10, resolve_only=False, target=["Opus 5.5"],
                sources_file=sources, allow_web=False, sensitive="redact",
            )
            args.prompt_file.write_text("question", encoding="utf-8")
            with mock.patch.object(run_ensemble, "parse_args", return_value=args), mock.patch.object(
                run_ensemble, "make_intelligence_catalog", return_value=EmptyIntelligenceCatalog()
            ), mock.patch.object(run_ensemble, "select_orchestrator_effort", return_value=""), mock.patch.object(
                run_ensemble, "run_named_targets", return_value=[]
            ) as named, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                run_ensemble.main()
            sent = named.call_args.args[2]
            self.assertIn("[REDACTED:account]", sent)
            self.assertIn("[REDACTED:iban]", sent)
            self.assertNotIn("12345678", sent)
            self.assertNotIn("3704", sent)
            saved = (Path(temp_dir) / "out" / "external_prompt.txt").read_text(encoding="utf-8")
            self.assertEqual(saved.count("[REDACTED:"), 2)


if __name__ == "__main__":
    unittest.main()
