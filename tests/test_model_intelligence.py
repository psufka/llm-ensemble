from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "ensemble" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import model_intelligence


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class ModelNormalizationTests(unittest.TestCase):
    def test_runtime_and_openrouter_names_share_a_key(self) -> None:
        self.assertEqual(
            model_intelligence.canonical_model_key("gemini-3.7-flash-high"),
            model_intelligence.canonical_model_key("google/gemini-3.7-flash"),
        )
        self.assertEqual(
            model_intelligence.canonical_model_key("claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)".split("\t")[0]),
            model_intelligence.canonical_model_key("anthropic/claude-sonnet-4.6"),
        )


class IntelligenceCatalogTests(unittest.TestCase):
    def test_openrouter_benchmark_fields_are_resolved_for_runtime_slug(self) -> None:
        payload = {
            "data": [
                {
                    "id": "google/gemini-3.7-flash",
                    "name": "Google: Gemini 3.7 Flash",
                    "benchmarks": {
                        "artificial_analysis": {
                            "intelligence_index": 56,
                            "coding_index": 76.1,
                            "agentic_index": 45.1,
                        }
                    },
                }
            ]
        }
        with mock.patch.object(
            model_intelligence.urllib.request,
            "urlopen",
            return_value=FakeResponse(json.dumps(payload)),
        ):
            score = model_intelligence.IntelligenceCatalog().lookup("gemini-3.7-flash-high", "gemini")

        self.assertIsNotNone(score)
        assert score is not None
        self.assertEqual(score.intelligence, 56.0)
        self.assertEqual(score.coding, 76.1)
        self.assertFalse(score.estimated)

    def test_artificial_analysis_page_fills_delisted_claude_score(self) -> None:
        catalog_payload = {
            "data": [
                {
                    "id": "anthropic/claude-opus-4.6",
                    "name": "Anthropic: Claude Opus 4.6",
                    "benchmarks": {"artificial_analysis": {}},
                }
            ]
        }
        page = "Claude Opus 4.6 scores 45 on the Artificial Analysis Intelligence Index."

        def response_for(request: object, timeout: float = 0) -> FakeResponse:
            del timeout
            url = getattr(request, "full_url", str(request))
            if "openrouter.ai" in url:
                return FakeResponse(json.dumps(catalog_payload))
            return FakeResponse(page)

        with mock.patch.object(model_intelligence.urllib.request, "urlopen", side_effect=response_for):
            score = model_intelligence.IntelligenceCatalog().lookup("claude-opus-4-6-thinking", "claude")

        self.assertIsNotNone(score)
        assert score is not None
        self.assertEqual(score.intelligence, 45.0)
        self.assertTrue(score.estimated)
        self.assertEqual(score.source, "Artificial Analysis")


if __name__ == "__main__":
    unittest.main()
