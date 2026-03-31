import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.constants import (
    DEBUG_DIR,
    EGTSR_DIR_NAME,
    LAST_GOOD_CAPSULE,
    RAW_EVENTS_DIR,
    REPORTS_DIR,
    RESUME_GATE,
)
from egtsr_runtime.paths import ensure_runtime_dirs


class PathTests(unittest.TestCase):
    def test_ensure_runtime_dirs_creates_standard_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = ensure_runtime_dirs(tmp_dir)
            root = Path(tmp_dir).resolve()
            egtsr_dir = root / EGTSR_DIR_NAME

            self.assertEqual(Path(paths.repo_root), root)
            self.assertEqual(Path(paths.egtsr_dir), egtsr_dir)
            self.assertEqual(Path(paths.last_good_capsule_path), egtsr_dir / LAST_GOOD_CAPSULE)
            self.assertEqual(Path(paths.resume_gate_path), egtsr_dir / RESUME_GATE)
            self.assertEqual(Path(paths.raw_events_dir), egtsr_dir / RAW_EVENTS_DIR)
            self.assertEqual(Path(paths.debug_dir), egtsr_dir / DEBUG_DIR)
            self.assertEqual(Path(paths.reports_dir), egtsr_dir / REPORTS_DIR)

            self.assertTrue(egtsr_dir.is_dir())
            self.assertTrue(Path(paths.raw_events_dir).is_dir())
            self.assertTrue(Path(paths.debug_dir).is_dir())
            self.assertTrue(Path(paths.reports_dir).is_dir())


if __name__ == "__main__":
    unittest.main()
