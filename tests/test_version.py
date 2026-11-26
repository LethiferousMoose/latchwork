import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from latchwork import settings, version  # noqa: E402


class TestVersion(unittest.TestCase):
    def test_semver(self):
        self.assertRegex(version.VERSION, r"^\d+\.\d+\.\d+$")

    def test_build_from_source(self):
        text = version.build()
        self.assertTrue(re.match(r"^(From source|Built )", text), text)
        with mock.patch.object(version, "git", return_value=None):
            self.assertEqual(version.build(), "From source")

    def test_frozen_app_folder(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            exe = os.path.abspath(os.path.join(os.sep, "apps", "Latchwork", "Latchwork.exe"))
            with mock.patch.object(sys, "executable", exe):
                self.assertEqual(settings.app_folder(), os.path.dirname(exe))
            app = os.path.join(os.path.abspath(os.sep), "apps", "Latchwork", "Latchwork.app", "Contents", "MacOS",
                               "Latchwork")
            with mock.patch.object(sys, "executable", app):
                self.assertEqual(settings.app_folder(), os.path.join(os.path.abspath(os.sep), "apps", "Latchwork"))
        self.assertTrue(os.path.isfile(os.path.join(settings.app_folder(), "latchwork.py")))


if __name__ == "__main__":
    unittest.main()
