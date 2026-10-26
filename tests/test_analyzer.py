"""Unit and integration tests for statistical analyzer and raw Mainnet dataset."""

from __future__ import annotations

import unittest
from pathlib import Path

from tx_order_lab.analyzer import (
    analyze_all_raw_blocks,
    pairwise_ordering_stats,
    spearman_rho,
)


class TestAnalyzerAndMainnetDataset(unittest.TestCase):
    def test_spearman_and_pairwise_stats_monotonic(self) -> None:
        indices = [0, 1, 2, 3, 4]
        neg_indices = [-i for i in indices]
        scores = [500.0, 400.0, 300.0, 200.0, 100.0]

        self.assertEqual(spearman_rho(neg_indices, scores), 1.0)
        stats = pairwise_ordering_stats(indices, scores)
        self.assertEqual(stats["concordance_pct"], 100.0)
        self.assertEqual(stats["kendall_tau"], 1.0)

        inv_scores = list(reversed(scores))
        self.assertEqual(spearman_rho(neg_indices, inv_scores), -1.0)
        inv_stats = pairwise_ordering_stats(indices, inv_scores)
        self.assertEqual(inv_stats["concordance_pct"], 0.0)
        self.assertEqual(inv_stats["kendall_tau"], -1.0)

    def test_raw_mainnet_dataset_meets_bounty_scope(self) -> None:
        raw_dir = Path(__file__).resolve().parents[1] / "data" / "raw"
        overall, cohorts = analyze_all_raw_blocks(raw_dir)

        self.assertTrue(overall["post_alpenglow_upgrade"])
        self.assertGreaterEqual(overall["total_validators_analyzed"], 6)
        self.assertGreaterEqual(overall["distinct_client_versions_count"], 3)
        self.assertGreater(overall["total_transactions_analyzed"], 3000)
        self.assertGreaterEqual(len(cohorts), 15)

        for b in overall["blocks"]:
            self.assertGreater(b["slot"], 461_000_000)
            self.assertGreater(b["total_transactions"], 200)
            self.assertIn("1", b["version_breakdown"])


if __name__ == "__main__":
    unittest.main()
