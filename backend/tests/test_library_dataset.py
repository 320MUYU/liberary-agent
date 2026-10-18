import json
from pathlib import Path
import unittest

from app.services.library_corpus import load_manifest
from scripts.evaluate_library import validate_splits, validate_suite

ROOT = Path(__file__).resolve().parents[2] / "evals" / "hust-library"


class LibraryDatasetTest(unittest.TestCase):
    def test_frozen_questions_are_supported_by_exact_official_snapshots_and_have_disjoint_splits(self):
        manifest = load_manifest(ROOT / "sources.json")
        calibration = json.loads((ROOT / "calibration.json").read_text(encoding="utf-8"))
        validation = json.loads((ROOT / "validation.json").read_text(encoding="utf-8"))
        for suite in (calibration, validation):
            validate_suite(suite, manifest, ROOT / "snapshots")
            self.assertEqual(suite["annotation_review"], "pending_human")
        validate_splits(calibration, validation)
        self.assertEqual(len(manifest.sources), 8)
        self.assertEqual(len(calibration["cases"]), 20)
        self.assertEqual(len(validation["cases"]), 30)
        categories = {case["category"] for suite in (calibration, validation) for case in suite["cases"]}
        self.assertTrue({"direct", "synonym", "follow_up", "cross_section", "no_answer", "scope_conflict", "injection"} <= categories)


