"""Tests for logging handler deduplication logic in settings."""

import importlib
import os
from unittest import mock

from django.test import SimpleTestCase


class TestLoggingHandlerDeduplication(SimpleTestCase):
    """Verify that console+ecs handlers are deduplicated to prevent duplicate log lines."""

    @staticmethod
    def _get_logging_handlers(env_value):
        """Simulate the LOGGING_HANDLERS computation from settings.py."""
        handlers = env_value.split(",")
        if "console" in handlers and "ecs" in handlers:
            handlers = [h for h in handlers if h != "console"]
        return handlers

    def test_console_only_unchanged(self):
        """DJANGO_LOG_HANDLERS=console should keep console."""
        result = self._get_logging_handlers("console")
        self.assertEqual(result, ["console"])

    def test_ecs_only_unchanged(self):
        """DJANGO_LOG_HANDLERS=ecs should keep ecs."""
        result = self._get_logging_handlers("ecs")
        self.assertEqual(result, ["ecs"])

    def test_console_and_ecs_deduplicates_to_ecs(self):
        """DJANGO_LOG_HANDLERS=console,ecs should drop console, keep ecs."""
        result = self._get_logging_handlers("console,ecs")
        self.assertEqual(result, ["ecs"])

    def test_ecs_and_console_deduplicates_to_ecs(self):
        """DJANGO_LOG_HANDLERS=ecs,console should drop console, keep ecs."""
        result = self._get_logging_handlers("ecs,console")
        self.assertEqual(result, ["ecs"])

    def test_console_ecs_watchtower_keeps_ecs_and_watchtower(self):
        """DJANGO_LOG_HANDLERS=console,ecs,watchtower should drop console only."""
        result = self._get_logging_handlers("console,ecs,watchtower")
        self.assertEqual(result, ["ecs", "watchtower"])

    def test_console_and_file_unchanged(self):
        """DJANGO_LOG_HANDLERS=console,file should keep both (no ecs conflict)."""
        result = self._get_logging_handlers("console,file")
        self.assertEqual(result, ["console", "file"])

    @mock.patch.dict(os.environ, {"DJANGO_LOG_HANDLERS": "console,ecs"})
    def test_settings_logging_config_uses_ecs_only(self):
        """When settings.py is loaded with console,ecs, LOGGING loggers should only have ecs."""
        # Reload settings to pick up the patched env var
        import rbac.settings as settings_module

        importlib.reload(settings_module)

        # All application loggers should use the deduplicated handlers
        for logger_name in ("rbac", "api", "management", "internal", "django"):
            handlers = settings_module.LOGGING["loggers"][logger_name]["handlers"]
            self.assertNotIn(
                "console",
                handlers,
                f"Logger '{logger_name}' should not have 'console' when 'ecs' is also configured",
            )
            self.assertIn("ecs", handlers, f"Logger '{logger_name}' should have 'ecs' handler")
