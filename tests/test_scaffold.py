"""T00 specification checks, executable without pytest using unittest."""
from pathlib import Path
import tomllib
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ScaffoldTests(unittest.TestCase):
    def test_rules_are_verbatim_source_section(self):
        text = (ROOT / 'BOOTSTRAP.md').read_text()
        expected = text.split('1. Permanent rules (copy verbatim into AGENTS.md)', 1)[1]
        expected = expected.split('2. Upstox data sources (what each layer uses)', 1)[0]
        self.assertEqual((ROOT / 'AGENTS.md').read_text(), expected.strip('\n') + '\n')

    def test_required_docs_and_packages(self):
        for name in ('IDEA', 'UPSTOX', 'ARCHITECTURE', 'DEFINITIONS', 'ROADMAP'):
            self.assertTrue((ROOT / f'docs/{name}.md').is_file(), name)
        for name in ('ingest', 'decode', 'trades', 'bars', 'layers/orderflow',
                     'layers/profile', 'layers/vwap', 'layers/smc', 'layers/levels',
                     'context', 'zones', 'setups', 'engine', 'research', 'ops', 'ui'):
            self.assertTrue((ROOT / f'src/orderflow/{name}/__init__.py').is_file(), name)

    def test_project_is_installable_src_package(self):
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertEqual(project['project']['name'], 'orderflow-zero')
        self.assertIn('pytest>=8', project['project']['optional-dependencies']['dev'])
        self.assertEqual(project['tool']['setuptools']['packages']['find']['where'], ['src'])
        self.assertEqual(project['tool']['pytest']['ini_options']['testpaths'], ['tests'])

    def test_known_bootstrap_defaults(self):
        config = yaml.safe_load((ROOT / 'config/default.yaml').read_text())
        expected = {
            'orderflow.diagonal.ratio': 3.0,
            'orderflow.diagonal.min_volume_percentile': 20,
            'orderflow.diagonal.stacked_levels': 3,
            'orderflow.sweep.levels': 3,
            'orderflow.iceberg.volume_factor': 3,
            'orderflow.iceberg.min_refills': 2,
            'orderflow.absorption.window_bars': 3,
            'orderflow.absorption.radius_ticks': 1,
            'orderflow.absorption.volume_factor': 3,
            'orderflow.absorption.max_extension_ticks': 2,
            'orderflow.exhaustion.extreme_bars': 20,
            'orderflow.exhaustion.delta_percentile': 90,
            'orderflow.exhaustion.confirmation_bars': 3,
            'orderflow.vpin.daily_volume_lookback_sessions': 20,
            'orderflow.vpin.buckets_per_day': 50,
            'orderflow.vpin.rolling_buckets': 50,
            'orderflow.vpin.unknown_buy_fraction': 0.5,
            'orderflow.kyle.window_minutes': 30,
            'profile.value_area_fraction': 0.7,
            'profile.smoothing_ticks': 3,
            'profile.composite_sessions': [5, 20],
            'profile.initial_balance_minutes': 60,
            'vwap.sigma_bands': [1, 2, 3],
            'vwap.reclaim_prior_closes': 2,
            'vwap.band_acceptance_closes': 3,
            'smc.timeframes_minutes': [1, 5, 15, 60],
            'smc.swing_bars_each_side': 2,
            'smc.atr_period': 14,
            'smc.break_basis': 'close',
            'smc.displacement.range_atr_multiple': 1.5,
            'smc.displacement.min_body_fraction': 0.6,
            'smc.fvg.min_ticks': 2,
            'smc.fvg.min_atr_multiple': 0.1,
            'smc.pools.min_swings': 2,
            'smc.pools.tolerance_atr_multiple': 0.1,
            'smc.sweep.penetration_ticks': 1,
            'smc.sweep.confirmation_bars': 3,
            'smc.dealing_range.midpoint': 0.5,
            'smc.dealing_range.ote_fraction': [0.62, 0.79],
            'levels.opening_range_minutes': [5, 15, 30],
            'levels.round_numbers.enabled': False,
            'context.vix.lookback_years': 1,
            'context.relative_strength.lookback_sessions': 5,
            'context.liquidity.lookback_sessions': 20,
            'context.events.announcement_lookback_minutes': 60,
            'zones.cluster_atr_multiple': 0.25,
            'zones.atr_period': 14,
            'zones.atr_timeframe_minutes': 5,
            'setups.s1.min_component_types': 2,
            'setups.s3.band_sigma': 2,
            'setups.s4.history_acceptance_closes': 3,
            'setups.plan.stop_buffer_atr_multiple': 0.1,
            'setups.plan.min_reward_risk': 1.5,
            'setups.plan.min_target_cost_multiple': 3,
            'setups.plan.forced_exit': '15:15',
            'validation.costs_bps': [10, 20, 30],
            'validation.live.outcome_minutes': [5, 15, 60],
            'validation.live.evaluation_recorded_days': [20, 60],
        }
        for path, value in expected.items():
            with self.subTest(path=path):
                actual = config
                for key in path.split('.'):
                    actual = actual[key]
                self.assertEqual(actual, value)
        self.assertEqual(config['runtime']['mode'], 'REPLAY')
        self.assertIsNone(config['setups']['plan']['risk_per_trade'])

    def test_no_implicit_defaults_for_undefined_parameters(self):
        config = yaml.safe_load((ROOT / 'config/default.yaml').read_text())
        self.assertIsNone(config['orderflow']['multi_level_ofi']['trailing_snapshots'])
        self.assertIsNone(config['context']['vix']['low_percentile'])
        self.assertIsNone(config['context']['vix']['high_percentile'])


if __name__ == '__main__':
    unittest.main()
