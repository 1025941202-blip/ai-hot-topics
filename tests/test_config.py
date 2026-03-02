from __future__ import annotations

import unittest

from test_support import PROJECT_ROOT, make_temp_project

from ai_hot_topics.config import load_runtime_config, load_scoring


class ConfigTests(unittest.TestCase):
    def test_load_runtime_config(self):
        cfg = load_runtime_config(PROJECT_ROOT)
        self.assertGreaterEqual(len(cfg.sources), 4)
        self.assertIn("AI", cfg.keywords.include_keywords)
        self.assertAlmostEqual(sum(cfg.scoring.weights.values()), 1.0)

    def test_scoring_validation_rejects_invalid_weights(self):
        temp_dir = make_temp_project()
        bad_file = temp_dir / "scoring.yaml"
        text = bad_file.read_text(encoding="utf-8").replace("china_fit: 0.15", "china_fit: 0.25")
        bad_file.write_text(text, encoding="utf-8")
        with self.assertRaises(ValueError):
            load_scoring(bad_file)


if __name__ == "__main__":
    unittest.main()

