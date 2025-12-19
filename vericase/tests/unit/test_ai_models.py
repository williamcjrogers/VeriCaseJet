import os
import sys
import unittest


# Provide minimal env for Settings validation during import.
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("USE_AWS_SERVICES", "true")
os.environ.setdefault("MINIO_BUCKET", "test-bucket")

# Ensure `api` package is importable when running from repo root.
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)


from api.app.ai_models import AIModelService  # noqa: E402


class TestAIModelResolution(unittest.TestCase):
    def test_resolve_friendly_names(self):
        cases = {
            "claude-sonnet-4": ("anthropic", "claude-sonnet-4-20250514"),
            "gpt-4o": ("openai", "gpt-4o"),
            "gpt-5.2-thinking": ("openai", "gpt-5.2-thinking"),
            "claude-opus-4.5": ("anthropic", "claude-opus-4.5"),
            "gemini-2-flash": ("gemini", "gemini-2.0-flash"),
            "gemini-2.5-flash-lite": ("gemini", "gemini-2.5-flash-lite"),
            "bedrock-nova-pro": ("bedrock", "amazon.nova-pro-v1:0"),
            "grok-4.1-fast": ("xai", "grok-4.1-fast"),
            "sonar-pro": ("perplexity", "sonar-pro"),
        }
        for friendly, expected in cases.items():
            resolved = AIModelService.resolve_model(friendly)
            self.assertIsNotNone(resolved, friendly)
            self.assertEqual(resolved["provider"], expected[0], friendly)
            self.assertEqual(resolved["model"], expected[1], friendly)

    def test_resolve_provider_model_string(self):
        resolved = AIModelService.resolve_model("openai:gpt-4o-mini")
        self.assertEqual(resolved["provider"], "openai")
        self.assertEqual(resolved["model"], "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
