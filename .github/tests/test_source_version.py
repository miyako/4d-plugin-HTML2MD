"""Source-only contract tests; fixtures live under the repository, not /tmp."""

import importlib.util
import re
import shutil
import stat
import sys
import unittest
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "source_version", ROOT / ".github/scripts/source_version.py"
)
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)

BASE = "3.7.9"
CMAKE = (
    'set_target_properties(HTML2MD PROPERTIES\n'
    '    MACOSX_BUNDLE_BUNDLE_VERSION "${SOURCE_VERSION}"\n'
    '    MACOSX_BUNDLE_SHORT_VERSION_STRING "${SOURCE_VERSION}"\n'
    ')\n'
)
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
    <key>CFBundleVersion</key><string>${MACOSX_BUNDLE_BUNDLE_VERSION}</string>
    <key>CFBundleShortVersionString</key><string>${MACOSX_BUNDLE_SHORT_VERSION_STRING}</string>
    <key>CFBundleExecutable</key><string>${MACOSX_BUNDLE_EXECUTABLE_NAME}</string>
</dict></plist>
"""


class SourceVersionTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / (".source-version-tests-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.write(source.VERSION_PATH, BASE + "\n")
        self.write(source.CMAKE, CMAKE)
        self.write(source.PLIST, PLIST)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def snapshot(self):
        return {
            path.relative_to(self.root): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for path in self.root.rglob("*") if path.is_file()
        }

    def assert_invalid(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            source.read(self.root)
        with self.assertRaises(ValueError):
            source.bump("patch", self.root)
        self.assertEqual(before, self.snapshot())

    def test_live_source_authority_no_repository_increment(self):
        before = {path: (ROOT / path).read_bytes() for path in source.SOURCE_PATHS}
        self.assertEqual(source.read(ROOT), before[source.VERSION_PATH].decode("utf-8").strip())
        self.assertEqual(
            source.SOURCE_PATHS,
            (Path("VERSION"), Path("HTML2MD/CMakeLists.txt"), Path("HTML2MD/Info.plist.in")),
        )
        for mode in ("patch", "minor", "major"):
            with self.subTest(mode=mode):
                for path, data in before.items():
                    (self.root / path).write_bytes(data)
                old = source.read(self.root)
                parts = list(map(int, old.split(".")))
                index = ("major", "minor", "patch").index(mode)
                parts[index] += 1
                parts[index + 1:] = [0] * (2 - index)
                expected = ".".join(map(str, parts))
                self.assertEqual(source.bump(mode, self.root), expected)
                self.assertEqual(source.read(self.root), expected)
                for path in (source.CMAKE, source.PLIST):
                    self.assertEqual((self.root / path).read_bytes(), before[path])
        self.assertEqual(before, {path: (ROOT / path).read_bytes() for path in before})

    def test_all_modes_stable(self):
        for mode, expected in (("patch", "3.7.10"), ("minor", "3.8.0"), ("major", "4.0.0")):
            with self.subTest(mode=mode):
                self.write(source.VERSION_PATH, BASE + "\n")
                self.assertEqual(source.bump(mode, self.root), expected)
                self.assertEqual(source.read(self.root), expected)

    def test_invalid_mode_no_writes(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            source.bump("revision", self.root)
        self.assertEqual(before, self.snapshot())

    def test_strict_version(self):
        for value in ("1.0", "v1.0.6", "01.0.6", "1.00.6", "1.0.06",
                      "-1.0.6", "1.0.6-rc1", " 1.0.6", "1.0.6 ",
                      "1.0.6\n\n", "1.0.6\n2.0.0", ""):
            with self.subTest(value=value):
                self.write(source.VERSION_PATH, value)
                self.assert_invalid()
        for ending in ("", "\n", "\r\n", "\r"):
            with self.subTest(ending=repr(ending)):
                self.write(source.VERSION_PATH, "0.0.0" + ending)
                self.assertEqual(source.read(self.root), "0.0.0")
                self.assertEqual(source.bump("patch", self.root), "0.0.1")
                self.assertEqual((self.root / source.VERSION_PATH).read_bytes(),
                                 ("0.0.1" + ending).encode())

    def test_cmake_count_invalid_and_drift(self):
        for key in source.KEYS:
            for replacement in (
                "", f'    {key} "${{SOURCE_VERSION}}"\n' * 2,
                f'    {key}\n', f'    {key} "1.0"\n',
                f'    {key} "3.7.8"\n', f'    {key} "${{{key}}}"\n',
                f'    {key} "$(SOURCE_VERSION)"\n', f'    {key} "${{UNKNOWN}}"\n',
                f'    {key} "${{SOURCE_VERSION}}" extra\n',
            ):
                with self.subTest(key=key, replacement=replacement):
                    self.write(source.CMAKE, CMAKE.replace(
                        f'    {key} "${{SOURCE_VERSION}}"\n', replacement))
                    self.assert_invalid()
        self.write(source.CMAKE, CMAKE + '# MACOSX_BUNDLE_BUNDLE_VERSION "9.9.9"\n')
        self.assertEqual(source.read(self.root), BASE)

    def test_plist_invalid_drift_and_references(self):
        for key, setting in source.PLIST_KEYS.items():
            for value in ("1.0", "3.7.8", "03.7.9", "$(SOURCE_VERSION)",
                          "${SOURCE_VERSION}", "$(MACOSX_BUNDLE_BUNDLE_VERSION)",
                          "${UNKNOWN}", "${" + setting + "}suffix", ""):
                with self.subTest(key=key, value=value):
                    self.write(source.PLIST, PLIST.replace("${" + setting + "}", value))
                    self.assert_invalid()
            self.write(source.PLIST, PLIST.replace(
                "<key>" + key + "</key><string>${" + setting + "}</string>",
                "<key>" + key + "</key><integer>3</integer>"))
            self.assert_invalid()
            self.write(source.PLIST, PLIST.replace(
                "</dict>", f"<key>{key}</key><string>{BASE}</string></dict>"))
            self.assert_invalid()
        for invalid in ("not xml", "<plist><dict>", "<plist><array/></plist>"):
            self.write(source.PLIST, invalid)
            self.assert_invalid()

    def test_valid_template_references_resolve_both_source_properties(self):
        for setting in source.KEYS:
            with self.subTest(setting=setting):
                self.write(source.VERSION_PATH, BASE + "\n")
                text = PLIST
                for original in source.KEYS:
                    text = text.replace("${" + original + "}", "${" + setting + "}")
                self.write(source.PLIST, text)
                before = (self.root / source.PLIST).read_bytes()
                self.assertEqual(source.read(self.root), BASE)
                self.assertEqual(source.bump("patch", self.root), "3.7.10")
                self.assertEqual((self.root / source.PLIST).read_bytes(), before)

    def test_absent_applicable_plist_keys_remain_absent(self):
        for keys in ((), ("CFBundleVersion",), ("CFBundleShortVersionString",)):
            with self.subTest(keys=keys):
                text = PLIST
                for key in keys:
                    text = re.sub(rf"\s*<key>{key}</key><string>[^<]*</string>", "", text)
                if not keys:
                    text = '<plist version="1.0"><dict/></plist>'
                self.write(source.PLIST, text)
                self.write(source.VERSION_PATH, BASE + "\n")
                before = (self.root / source.PLIST).read_bytes()
                self.assertEqual(source.bump("minor", self.root), "3.8.0")
                self.assertEqual((self.root / source.PLIST).read_bytes(), before)

    def test_literal_co_bump_preserves_bytes_bom_endings_and_modes(self):
        for bom in (b"", b"\xef\xbb\xbf"):
            with self.subTest(bom=bom):
                cmake = CMAKE.replace("${SOURCE_VERSION}", BASE, 1).replace(
                    '"${SOURCE_VERSION}"', BASE, 1)
                plist = PLIST.replace("${MACOSX_BUNDLE_BUNDLE_VERSION}", BASE).replace(
                    "${MACOSX_BUNDLE_SHORT_VERSION_STRING}", BASE)
                for path, text in ((source.VERSION_PATH, BASE + "\r\n"),
                                   (source.CMAKE, cmake), (source.PLIST, plist)):
                    lines = text.splitlines()
                    endings = ("\r\n", "\n", "\r")
                    mixed = "".join(line + endings[index % 3]
                                    for index, line in enumerate(lines))
                    (self.root / path).write_bytes(bom + mixed.encode())
                    (self.root / path).chmod(0o640)
                before = self.snapshot()
                self.assertEqual(source.bump("patch", self.root), "3.7.10")
                self.assertEqual(source.read(self.root), "3.7.10")
                for path in source.SOURCE_PATHS:
                    data, mode = before[path]
                    self.assertEqual((self.root / path).read_bytes(),
                                     data.replace(BASE.encode(), b"3.7.10"))
                    self.assertEqual(stat.S_IMODE((self.root / path).stat().st_mode), mode)

    def test_excluded_tree_is_not_read_or_written(self):
        excluded = (
            "HTML2MD/HTML2MD-4dplugin.h", "HTML2MD/manifest.json",
            "HTML2MD/constants.xlf", "deps/html2md/CMakeLists.txt",
            "4D-Plugin-SDK/4D Plugin API/4DPluginAPI.h",
            "HTML2MD/HTML2MD-test/Project/HTML2MD.4DProject",
            "HTML2MD/HTML2MD-test/Plugins/HTML2MD.bundle/Contents/Info.plist",
            "HTML2MD/HTML2MD-test/Plugins/HTML2MD.bundle/Contents/MacOS/HTML2MD",
            "HTML2MD/File.xcodeproj/project.pbxproj", "HTML2MD/English.lproj/InfoPlist.strings",
        )
        for path in excluded:
            self.write(Path(path), "invalid metadata 999.0.0\n")
        before = self.snapshot()
        self.assertEqual(source.bump("major", self.root), "4.0.0")
        after = self.snapshot()
        self.assertEqual(set(before), set(after))
        for path in excluded:
            self.assertEqual(before[Path(path)], after[Path(path)])


if __name__ == "__main__":
    unittest.main()
