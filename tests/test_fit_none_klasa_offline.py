"""8.11.: the daily weight fit crashed for 2.7 days on one shadow point with klasa NULL (sorted() of str and None).
A row without a class must not stop the run; it learns with the default class."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learn import fit, outcomes  # noqa: E402

NOW = 1793390000


class NoneKlasa(unittest.TestCase):
    def test_fit_runs_with_none_class(self):
        rows = [{"klasa": "moonshot", "ts": NOW - 3600, "features": {"a": 1}, "hit": True, "max_ret": 1.0}]
        sh = [{"klasa": None, "ts": NOW - 3600, "features": {"a": 1}, "hit": False, "max_ret": 0.0, "w": 1.0}]
        cfg = {**outcomes.config(), "cilj": "zarada"}
        with mock.patch.object(outcomes, "rows", return_value=(rows, {"moonshot": 2.0, None: 1.0})), \
                mock.patch.object(outcomes, "shadow_rows", return_value=sh), \
                mock.patch("learn.store.log_run"), mock.patch("learn.store.prune_empty"):
            rep = fit.run(mock.MagicMock(), cfg=cfg, now=NOW, apply=False, base={"a": 10})
        self.assertEqual(sorted(r["klasa"] for r in rep), ["default", "moonshot"])


if __name__ == "__main__":
    unittest.main()
