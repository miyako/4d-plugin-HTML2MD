"""VERSION-authoritative source metadata; generated bundles and counters are excluded."""

import argparse
import plistlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.parsers.expat import ExpatError

sys.dont_write_bytecode = True

VERSION_PATH = Path("VERSION")
CMAKE = Path("HTML2MD/CMakeLists.txt")
PLIST = Path("HTML2MD/Info.plist.in")
SOURCE_PATHS = (VERSION_PATH, CMAKE, PLIST)
STRICT_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
KEYS = ("MACOSX_BUNDLE_BUNDLE_VERSION", "MACOSX_BUNDLE_SHORT_VERSION_STRING")
SETTING = re.compile(
    r"(?m)^[ \t]*(MACOSX_BUNDLE_BUNDLE_VERSION|MACOSX_BUNDLE_SHORT_VERSION_STRING)"
    r"\b[^\r\n]*"
)
VALUE = re.compile(
    r'([ \t]*(?:MACOSX_BUNDLE_BUNDLE_VERSION|MACOSX_BUNDLE_SHORT_VERSION_STRING)'
    r'[ \t]+)("([^"\r\n]*)"|([^ \t\r\n#()]+))([ \t]*(?:#[^\r\n]*)?)'
)
PLIST_KEYS = {
    "CFBundleVersion": KEYS[0],
    "CFBundleShortVersionString": KEYS[1],
}
PLIST_VALUE = re.compile(
    r"(<key>CFBundle(?:ShortVersionString|Version)</key>\s*<string>)([^<]*)(</string>)"
)


def _decode(data):
    return data.decode("utf-8-sig")


def _validate(contents):
    authority = _decode(contents[VERSION_PATH])
    if not re.fullmatch(STRICT_VERSION + r"(?:\r\n|\r|\n)?", authority):
        raise ValueError("VERSION must contain one strict X.Y.Z version")
    version = authority.rstrip("\r\n")
    fields = {key: [] for key in KEYS}
    for setting in SETTING.finditer(_decode(contents[CMAKE])):
        match = VALUE.fullmatch(setting[0])
        if match is None:
            raise ValueError(f"Invalid CMake version setting: {setting[1]}")
        fields[setting[1]].append(match[3] if match[3] is not None else match[4])
    for key, values in fields.items():
        if len(values) != 1:
            raise ValueError(f"Expected one CMake setting for {key}")
        if values[0] not in (version, "${SOURCE_VERSION}"):
            raise ValueError(f"{key} is invalid, unresolved or has drifted from VERSION")

    try:
        xml = _decode(contents[PLIST])
        document = ET.fromstring(xml)
        plist = plistlib.loads(xml.encode("utf-8"))
    except (ValueError, ET.ParseError, ExpatError, plistlib.InvalidFileException) as error:
        raise ValueError("Source Info.plist.in is invalid") from error
    if not isinstance(plist, dict) or document.tag != "plist":
        raise ValueError("Source Info.plist.in must be a dictionary")
    references = {"${" + setting + "}" for setting in KEYS}
    for key in PLIST_KEYS:
        count = sum(element.text == key for element in document.iter("key"))
        if count > 1:
            raise ValueError(f"Duplicate source plist key: {key}")
        if key not in plist:
            continue
        value = plist[key]
        if not isinstance(value, str) or value not in references | {version}:
            raise ValueError(f"{key} is invalid, unresolved or has drifted from VERSION")
        # Keep updates bounded to the source template's actual string elements.
        pattern = rf"<key>{key}</key>\s*<string>[^<]*</string>"
        if len(re.findall(pattern, xml)) != 1:
            raise ValueError(f"Unsupported source plist representation: {key}")
    return version


def _contents(root):
    return {path: (Path(root) / path).read_bytes() for path in SOURCE_PATHS}


def read(root=Path(".")):
    return _validate(_contents(root))


def _encode_like(original, text):
    return text.encode("utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8")


def bump(mode, root=Path(".")):
    if mode not in ("patch", "minor", "major"):
        raise ValueError("Bump mode must be patch, minor or major")
    contents = _contents(root)
    current = _validate(contents)
    index = ("major", "minor", "patch").index(mode)
    parts = list(map(int, current.split(".")))
    parts[index] += 1
    parts[index + 1:] = [0] * (2 - index)
    new = ".".join(map(str, parts))

    def cmake_replace(setting):
        match = VALUE.fullmatch(setting[0])
        value = match[3] if match[3] is not None else match[4]
        return setting[0] if value == "${SOURCE_VERSION}" else setting[0].replace(
            current, new, 1
        )

    transforms = {
        VERSION_PATH: lambda text: new + text[len(current):],
        CMAKE: lambda text: SETTING.sub(cmake_replace, text),
        PLIST: lambda text: PLIST_VALUE.sub(
            lambda match: match[0] if match[2].startswith("${") else
            f"{match[1]}{new}{match[3]}", text
        ),
    }
    updated = {
        path: _encode_like(data, transforms[path](_decode(data)))
        for path, data in contents.items()
    }
    if _validate(updated) != new:
        raise ValueError("Bumped metadata did not validate")
    for path, data in updated.items():
        if data != contents[path]:
            (Path(root) / path).write_bytes(data)
    return new


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bump", choices=("patch", "minor", "major"))
    args = parser.parse_args()
    print(bump(args.bump) if args.bump else read())
