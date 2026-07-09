import unittest

from weather_edge import BucketInput, build_pnl_curve


class PnLCurveTests(unittest.TestCase):
    def test_builds_complete_bucket_level_pnl_curve(self):
        curve = build_pnl_curve(
            [
                BucketInput("31C", price=0.10, shares=0, model_probability=0.04),
                BucketInput("32C", price=0.18, shares=5, model_probability=0.22),
                BucketInput("33C", price=0.35, shares=10, model_probability=0.42),
                BucketInput("34C", price=0.12, shares=2, model_probability=0.09),
            ]
        )

        self.assertAlmostEqual(curve.total_cost, 4.64)
        self.assertEqual([row.bucket for row in curve.rows], ["31C", "32C", "33C", "34C"])
        self.assertAlmostEqual(curve.rows[0].pnl_if_wins, -4.64)
        self.assertAlmostEqual(curve.rows[1].pnl_if_wins, 0.36)
        self.assertAlmostEqual(curve.rows[2].pnl_if_wins, 5.36)
        self.assertAlmostEqual(curve.rows[3].pnl_if_wins, -2.64)
        self.assertEqual(curve.structure, "multi_bucket_dutching_with_tail_or_neighbor_protection")

    def test_flags_death_gap_for_uncovered_high_probability_bucket(self):
        curve = build_pnl_curve(
            [
                BucketInput("31C", price=0.08, shares=1, model_probability=0.05),
                BucketInput("32C", price=0.20, shares=0, model_probability=0.16),
                BucketInput("33C", price=0.40, shares=4, model_probability=0.50),
            ],
            max_uncovered_probability=0.10,
        )

        self.assertEqual(len(curve.death_gaps), 1)
        self.assertEqual(curve.death_gaps[0].bucket, "32C")
        self.assertAlmostEqual(curve.max_uncovered_probability, 0.16)

    def test_rejects_invalid_bucket_inputs(self):
        with self.assertRaisesRegex(ValueError, "price"):
            build_pnl_curve([BucketInput("33C", price=1.2, shares=1, model_probability=0.5)])

        with self.assertRaisesRegex(ValueError, "model_probability"):
            build_pnl_curve([BucketInput("33C", price=0.2, shares=1, model_probability=-0.1)])
