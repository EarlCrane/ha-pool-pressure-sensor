"""Tests for the Home Assistant-independent recovery model."""

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).parents[1]
PACKAGE = "custom_components.pool_filter_analytics"

# Load the pure model without requiring a local Home Assistant installation.
custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", custom_components)
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components" / "pool_filter_analytics")]
sys.modules.setdefault(PACKAGE, package)

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.models",
    ROOT / "custom_components" / "pool_filter_analytics" / "models.py",
)
assert spec is not None and spec.loader is not None
models = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = models
spec.loader.exec_module(models)

AnalyticsEngine = models.AnalyticsEngine


class AnalyticsEngineTest(unittest.TestCase):
    """Exercise event transitions, both requested models, and persistence."""

    def setUp(self) -> None:
        self.start = datetime(2026, 8, 1, 12, tzinfo=UTC)
        self.engine = AnalyticsEngine(sample_interval_seconds=60)
        self.engine.handle_sample(self.start, 28.5)

    def test_bump_recovery_completes_and_fits_tau(self) -> None:
        """A clean exponential recovery produces τ and recovery duration."""
        self.engine.mark_bump(self.start, 28.5)
        self.engine.handle_sample(self.start + timedelta(minutes=1), 0.0)
        self.engine.handle_sample(self.start + timedelta(minutes=2), 25.0)

        tau_hours = 2.0
        for minute in range(12, 252, 10):
            elapsed = (minute - 2) / 60
            pressure = 28.5 - (28.5 - 25.0) * models.math.exp(
                -elapsed / tau_hours
            )
            self.engine.handle_sample(
                self.start + timedelta(minutes=minute), pressure
            )

        self.assertEqual(self.engine.state, "recovering")
        self.assertIsNotNone(self.engine.tau_hours)
        self.assertAlmostEqual(self.engine.tau_hours, tau_hours, delta=0.08)
        self.assertIsNotNone(self.engine.fit_quality)
        self.assertGreater(self.engine.fit_quality, 0.99)

        self.engine.handle_sample(self.start + timedelta(hours=5), 28.5)
        self.assertEqual(self.engine.state, "normal")
        self.assertAlmostEqual(self.engine.last_recovery_hours, 4.9667, places=3)
        self.assertEqual(self.engine.recovery_progress, 100.0)

    def test_restart_requires_observed_offline_state(self) -> None:
        """A normal pressure fluctuation must not start a recovery."""
        self.engine.mark_bump(self.start, 28.5)
        self.engine.handle_sample(self.start + timedelta(minutes=1), 25.0)
        self.assertEqual(self.engine.state, "awaiting_restart")

        self.engine.handle_sample(self.start + timedelta(minutes=2), 0.0)
        self.engine.handle_sample(self.start + timedelta(minutes=3), 25.0)
        self.assertEqual(self.engine.state, "recovering")
        self.assertEqual(self.engine.pressure_after, 25.0)

    def test_backwash_resets_cycle(self) -> None:
        """A full backwash clears bump metrics and starts a new cycle."""
        self.engine.mark_bump(self.start, 28.5)
        reset_time = self.start + timedelta(hours=1)
        self.engine.mark_backwash(reset_time, 18.0)

        self.assertEqual(self.engine.state, "normal")
        self.assertEqual(self.engine.bump_count, 0)
        self.assertEqual(self.engine.cycle_started_at, reset_time)
        self.assertIsNone(self.engine.pressure_before)

    def test_state_round_trip(self) -> None:
        """An in-progress recovery survives serialization and restore."""
        self.engine.mark_bump(self.start, 28.5)
        self.engine.handle_sample(self.start + timedelta(minutes=1), 0.0)
        self.engine.handle_sample(self.start + timedelta(minutes=2), 25.0)
        self.engine.handle_sample(self.start + timedelta(minutes=12), 25.3)

        restored = AnalyticsEngine.from_dict(
            self.engine.as_dict(),
            offline_threshold=2.0,
            minimum_drop=0.5,
            sample_interval_seconds=60,
        )

        self.assertEqual(restored.state, "recovering")
        self.assertEqual(restored.pressure_before, 28.5)
        self.assertEqual(restored.pressure_after, 25.0)
        self.assertEqual(len(restored.samples), 2)


if __name__ == "__main__":
    unittest.main()
