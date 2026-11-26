import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from latchwork import settings, version  # noqa: E402


class TestVersion(unittest.TestCase):
    def test_from_describe(self):
        f = version.from_describe
        self.assertEqual(f("v1.2.0-0-gabc1234"), "1.2.0")
        self.assertEqual(f("v1.2.0-3-gabc1234"), "1.2.1.dev3+gabc1234")
        self.assertEqual(f("v1.2.0-3-gabc1234-dirty"), "1.2.1.dev3+gabc1234.dirty")
        self.assertEqual(f("v1.2.0-0-gabc1234-dirty"), "1.2.0+gabc1234.dirty")
        self.assertEqual(f("v10.20.30-12-gdeadbeef"), "10.20.31.dev12+gdeadbeef")
        self.assertEqual(f(None, 42, "abc1234"), "0.0.1.dev42+gabc1234")   # no release yet
        self.assertEqual(f(None, 42, "abc1234.dirty"), "0.0.1.dev42+gabc1234.dirty")
        self.assertEqual(f("release-1", 5, "abc1234"), "0.0.1.dev5+gabc1234")  # not a v tag

    def test_bump(self):
        self.assertEqual(version.bump(None, "major"), "1.0.0")    # the first release
        self.assertEqual(version.bump("1.2.3", "major"), "2.0.0")
        self.assertEqual(version.bump("1.2.3", "minor"), "1.3.0")
        self.assertEqual(version.bump("1.2.3", "patch"), "1.2.4")
        with self.assertRaises(ValueError):
            version.bump("1.2.3", "huge")

    def test_from_source(self):
        self.assertTrue(re.match(r"^(\d+\.\d+\.\d+|unknown)", version.version()))
        self.assertTrue(re.match(r"^(From source|Built )", version.build()))
        with mock.patch.object(version, "git", return_value=None):
            self.assertEqual((version.version(), version.build()), ("unknown", "From source"))

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

    def test_translocated(self):
        exe = "Latchwork.app/Contents/MacOS/Latchwork"
        hidden = "/private/var/folders/xy/T/AppTranslocation/1A2B/d/" + exe
        moved = "/Users/me/Latchwork/" + exe
        self.assertFalse(settings.translocated(hidden))     # from source: never
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertTrue(settings.translocated(hidden))
                self.assertFalse(settings.translocated(moved))
            with mock.patch.object(sys, "platform", "win32"):
                self.assertFalse(settings.translocated(hidden))


if __name__ == "__main__":
    unittest.main()
