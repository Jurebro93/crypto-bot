"""10.11.: the weight fit does not redo a class whose outcomes have not changed since its last finished fit."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import fit, outcomes, weights  # noqa: E402

NOW = 1793390000


def rows(n):
    return [{"klasa": "moonshot", "ts": NOW - 400 * 3600 + i * 3600, "features": {"a": (i % 3), "b": 1},
             "hit": i % 3 == 0, "max_ret": 1.0 if i % 3 == 0 else 0.0, "w": 1.0} for i in range(n)]


class Skip(unittest.TestCase):
    def setUp(self):
        self.old = weights.LEARNED_DIR
        weights.LEARNED_DIR = tempfile.mkdtemp()

    def tearDown(self):
        weights.LEARNED_DIR = self.old

    def run_fit(self, sh):
        cfg = {**outcomes.config(), "cilj": "zarada", "min_rows_zarada": 30}
        with mock.patch.object(outcomes, "rows", return_value=([], {})), \
                mock.patch.object(outcomes, "shadow_rows", return_value=sh), \
                mock.patch("learn.store.log_run"), mock.patch("learn.store.prune_empty"), \
                mock.patch.object(weights, "save"):
            return fit.run(mock.MagicMock(), cfg=cfg, now=NOW, apply=True, base={"a": 10, "b": 10})

    def test_second_run_skipped_until_new_outcomes(self):
        first = self.run_fit(rows(200))[0]
        self.assertFalse(first.get("skipped"))
        self.assertIsNotNone(first["new"])
        self.assertTrue(self.run_fit(rows(200))[0].get("skipped"))
        self.assertFalse(self.run_fit(rows(210))[0].get("skipped"))


if __name__ == "__main__":
    unittest.main()
