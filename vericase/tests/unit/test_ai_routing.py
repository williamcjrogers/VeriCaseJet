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


from api.app.ai_router import AdaptiveModelRouter, RoutingConfig, RoutingStrategy  # noqa: E402
from api.app.ai_fallback import AIFallbackChain  # noqa: E402
from api.app.ai_settings import AISettings  # noqa: E402


class TestAIRoutingAndFallback(unittest.TestCase):
    def setUp(self):
        self._orig_get_function_config = AISettings.get_function_config

    def tearDown(self):
        AISettings.get_function_config = self._orig_get_function_config

    def test_router_uses_ai_settings_fallback_chain(self):
        # Patch AISettings to provide a custom chain.
        def _fake_cfg(cls, function_name, db=None):
            return {
                "fallback_chain": [
                    ("openai", "gpt-4o-mini"),
                    ("gemini", "gemini-2.0-flash"),
                ]
            }

        AISettings.get_function_config = classmethod(_fake_cfg)

        router = AdaptiveModelRouter(
            db=None,
            config=RoutingConfig(strategy=RoutingStrategy.FALLBACK),
        )
        router.openai_key = "x"
        router.gemini_key = "y"
        router.anthropic_key = ""
        router.bedrock_enabled = False

        decision = router.route("quick_search", strategy=RoutingStrategy.FALLBACK)
        self.assertEqual(decision.provider, "openai")
        self.assertEqual(decision.model_id, "gpt-4o-mini")

    def test_router_falls_back_to_static_defaults(self):
        # No fallback_chain in config -> should use TASK_DEFAULTS.
        AISettings.get_function_config = classmethod(lambda cls, function_name, db=None: {})

        router = AdaptiveModelRouter(
            db=None,
            config=RoutingConfig(strategy=RoutingStrategy.FALLBACK),
        )
        router.openai_key = "x"
        router.gemini_key = "y"
        router.bedrock_enabled = False  # makes bedrock options unavailable

        decision = router.route("quick_search", strategy=RoutingStrategy.FALLBACK)
        self.assertEqual(decision.provider, "gemini")

    def test_fallback_chain_reads_ai_settings(self):
        def _fake_cfg(cls, function_name, db=None):
            return {
                "fallback_chain": [
                    ("gemini", "gemini-2.0-flash"),
                    ("openai", "gpt-4o"),
                ]
            }

        AISettings.get_function_config = classmethod(_fake_cfg)

        chain = AIFallbackChain(db=None)
        resolved = chain.get_chain("quick_search")
        self.assertEqual(resolved[0], ("gemini", "gemini-2.0-flash"))
        self.assertEqual(resolved[1], ("openai", "gpt-4o"))


if __name__ == "__main__":
    unittest.main()

