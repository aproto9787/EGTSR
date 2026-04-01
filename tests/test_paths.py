import os
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.constants import (
    DEBUG_DIR,
    LAST_GOOD_CAPSULE,
    RAW_EVENTS_DIR,
    REPORTS_DIR,
    RESUME_GATE,
)
from egtsr_runtime.paths import ensure_runtime_dirs


def _with_egtsr_home(fn):
    """Decorator: run fn with a temporary EGTSR_HOME, restore afterwards."""
    def wrapper(*args, **kwargs):
        orig = os.environ.get("EGTSR_HOME")
        with tempfile.TemporaryDirectory() as egtsr_home:
            os.environ["EGTSR_HOME"] = egtsr_home
            try:
                return fn(*args, egtsr_home=egtsr_home, **kwargs)
            finally:
                if orig is not None:
                    os.environ["EGTSR_HOME"] = orig
                else:
                    os.environ.pop("EGTSR_HOME", None)
    return wrapper


class PathTests(unittest.TestCase):
    @_with_egtsr_home
    def test_ensure_runtime_dirs_creates_standard_structure(self, egtsr_home: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = ensure_runtime_dirs(tmp_dir)
            root = Path(tmp_dir).resolve()

            self.assertEqual(Path(paths.repo_root), root)

            # egtsr_dir should be under EGTSR_HOME/projects/<hash>/
            egtsr_dir = Path(paths.egtsr_dir)
            self.assertTrue(str(egtsr_dir).startswith(egtsr_home))
            self.assertIn("projects", egtsr_dir.parts)

            self.assertEqual(Path(paths.last_good_capsule_path), egtsr_dir / LAST_GOOD_CAPSULE)
            self.assertEqual(Path(paths.resume_gate_path), egtsr_dir / RESUME_GATE)
            self.assertEqual(Path(paths.raw_events_dir), egtsr_dir / RAW_EVENTS_DIR)
            self.assertEqual(Path(paths.debug_dir), egtsr_dir / DEBUG_DIR)
            self.assertEqual(Path(paths.reports_dir), egtsr_dir / REPORTS_DIR)

            self.assertTrue(egtsr_dir.is_dir())
            self.assertTrue(Path(paths.raw_events_dir).is_dir())
            self.assertTrue(Path(paths.debug_dir).is_dir())
            self.assertTrue(Path(paths.reports_dir).is_dir())

    @_with_egtsr_home
    def test_same_repo_root_gives_same_shard(self, egtsr_home: str) -> None:
        """Same repo_root always maps to the same project shard."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths1 = ensure_runtime_dirs(tmp_dir)
            paths2 = ensure_runtime_dirs(tmp_dir)
            self.assertEqual(paths1.egtsr_dir, paths2.egtsr_dir)
            self.assertEqual(paths1.db_path, paths2.db_path)

    @_with_egtsr_home
    def test_different_repo_roots_give_different_shards(self, egtsr_home: str) -> None:
        with tempfile.TemporaryDirectory() as tmp1, \
             tempfile.TemporaryDirectory() as tmp2:
            paths1 = ensure_runtime_dirs(tmp1)
            paths2 = ensure_runtime_dirs(tmp2)
            self.assertNotEqual(paths1.egtsr_dir, paths2.egtsr_dir)


if __name__ == "__main__":
    unittest.main()
