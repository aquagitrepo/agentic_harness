"""The ecc-router index must cover the whole skill library and stay compact."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_skill_index as index  # noqa: E402


class SkillIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = index.skills()
        cls.router = (index.ROUTER / "SKILL.md").read_text(encoding="utf-8")

    def test_index_matches_the_library(self):
        # Fails when a library skill is added, removed, or edited without rerunning the script.
        text, full = index.render(self.router, self.entries)
        self.assertEqual(text, self.router)
        self.assertEqual(full, (index.ROUTER / "index-full.md").read_text(encoding="utf-8"))

    def test_every_skill_has_a_description(self):
        self.assertGreater(len(self.entries), 0)
        self.assertEqual([name for name, desc in self.entries if not desc], [])

    def test_router_stays_compact(self):
        # The full table it replaced was ~75 KB, loaded on every consult.
        self.assertLess(len(self.router.encode("utf-8")), 32_000)

    def test_hooks_are_short(self):
        for name, desc in self.entries:
            self.assertLessEqual(len(index.hook(desc)), index.HOOK_CHARS + 1, name)


if __name__ == "__main__":
    unittest.main()
