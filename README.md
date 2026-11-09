# 4d-plugin-HTML2MD

A 4D plugin that converts HTML to Markdown using the [html2md](https://github.com/tim-gromeyer/html2md) library.

## Requirements

- 4D v21.1 or later

## Installation

Download the latest release from the [Releases](../../releases) page.

### macOS & Windows (single download)

1. Download the `.zip` from the release
2. Extract to get the `HTML2MD.bundle` folder
3. Copy the `.bundle` into your 4D application's **Plugins** folder (or your database's **Plugins** folder)
4. Restart 4D

### macOS only (notarized DMG)

1. Download the `.dmg` from the release
2. Mount it and copy the `.bundle` into your **Plugins** folder
3. Restart 4D

## Commands

### `HTML2MD`

```4d
$md:=HTML2MD($html)
```

| Parameter | Type | Description |
|---|---|---|
| `$html` | Text | HTML content to convert |
| `$md` | Text | Resulting Markdown |

**Example:**

```4d
$html:="<h1>Hello</h1><p>This is <strong>bold</strong> and <em>italic</em>.</p>"
$md:=HTML2MD($html)
// $md = "# Hello\n\nThis is **bold** and _italic_.\n\n"
```

## Building from Source

### Prerequisites

- CMake 3.20+
- Xcode (macOS) or Visual Studio 2022 (Windows)

### Clone

```bash
git clone --recurse-submodules https://github.com/{owner}/html2md-plugin.git
cd html2md-plugin
```

### Build (macOS)

```bash
cd HTML2MD
mkdir -p cmake-build && cd cmake-build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
```

### Build (Windows)

```pwsh
cd HTML2MD
mkdir cmake-build; cd cmake-build
cmake .. -G "Visual Studio 17 2022" -A x64
cmake --build . --config Release
```

### Run Tests

Requires [tool4d](https://developer.4d.com/docs/Admin/cli/) (free, no license needed):

```bash
/path/to/tool4d --dataless --startup-method=test_all --project=$(pwd)/HTML2MD-test/Project/HTML2MD.4DProject
```

## CI/CD

Version changes and publication are separate, manual GitHub Actions operations:

| Workflow | Trigger | Purpose |
|---|---|---|
| `test.yml` — **Build and Test** | Any tag push (`*`) / manual | Existing macOS + Windows build and 4D tests |
| `bump-version.yml` — **Bump version** | Manual, patch/minor/major choice | Source-only version commit on the selected existing branch |
| `release.yml` — **Build** | Manual, zero inputs | Build, sign, notarize, and publish the selected source SHA |

### Source version

Root `VERSION` is the sole authority: one strict `X.Y.Z` (no leading zeros,
prefixes, suffixes, or whitespace; an optional final line ending is allowed).
The migration retains `1.0.6`; it does not increment source history.
`HTML2MD/CMakeLists.txt` reads `../VERSION` and uses `${SOURCE_VERSION}` for both
`MACOSX_BUNDLE_BUNDLE_VERSION` and `MACOSX_BUNDLE_SHORT_VERSION_STRING`.
The source `HTML2MD/Info.plist.in` retains its valid `${MACOSX_BUNDLE_*}`
references. Applicable literal versions must agree with `VERSION` and co-bump;
absent template keys stay absent.

`.github/scripts/source_version.py` validates this bounded contract (exactly
one CMake property per version key). Its `SOURCE_PATHS` are only `VERSION`,
`HTML2MD/CMakeLists.txt`, and `HTML2MD/Info.plist.in`. Bumps preserve BOMs,
line endings, file modes, and unchanged reference bytes. There is no separate
header version contract, manifest version key, Xcode project, or localized
source version to update. Checked-in prebuilt bundles, dependencies, SDK files,
4D project/schema versions, and counters are never version-bump targets.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 .github/scripts/source_version.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s .github/tests -p test_source_version.py
```

### Bump, then build

1. Run **Bump version**, select an existing branch, and choose `patch`, `minor`,
   or `major`. The selected immutable `github.sha` must still be that branch's
   remote tip. The clean checkout produces a source-only commit that is a
   direct child of that SHA and pushes only the branch, not tags.
2. The pre-push guard checks exactly one advertised update: the remote ref
   equals the selected branch ref, its advertised old SHA equals the selected
   SHA, the local ref and SHA equal the new commit SHA, `HEAD` equals that SHA,
   and the new commit has exactly the selected SHA as its sole parent.
   Missing/up-to-date updates and moved-branch races fail closed. Tag following
   is disabled. A bump does **not** automatically start **Build**.
3. Run **Build** separately on the desired branch/ref. It has no version or tag
   input: the selected immutable `github.sha` and validated source version
   determine tag `vX.Y.Z`. Windows x64 builds first, then macOS universal
   (`arm64;x86_64`). The Windows binary is merged into `HTML2MD.bundle`;
   release assets are `HTML2MD-X.Y.Z.zip` and `HTML2MD-X.Y.Z.dmg`.

Existing universal-binary verification, Developer ID signing and verification,
ZIP/DMG notarization, DMG stapling, and required-secret gates remain in place.
Publication checks remote tags and authenticated, **paginated** draft and
published releases both before native work and immediately before publication.
It creates the tag at the exact selected SHA, then creates the release and
uploads assets. An existing tag/release is an error, even at the same SHA.
There is no DELETE, PATCH, asset clobbering, automatic retry, or partial-state
repair. If tag creation, release creation, or an upload only partly succeeds,
inspect the retained remote state and recover manually before another attempt.
Repository-wide release concurrency serializes publication without cancelling
a running release.

Branch pushes do not trigger CI. Publication's new tag may invoke the unchanged
**Build and Test** workflow; its any-tag (`*`) push and manual triggers remain.

### Native build caveats

The dependency and 4D SDK trees are checked in despite `.gitmodules` entries;
inspect their actual contents rather than assuming submodule initialization
updates them. CMake uses those trees and outputs into the checked-in
`HTML2MD/HTML2MD-test/Plugins` tree, so native builds can dirty prebuilt files.
The top-level CMake file supports macOS and Windows, not a Linux plugin build.
tool4d is an external prerequisite (the 4D project declares compatibility
`2101`); it is not supplied by the source-version helper. The earlier local
test command's project path should include `HTML2MD/` when run from the
repository root. Source-version Python tests do not run native builds, 4D tests,
signing, notarization, or Actions.

### Required Secrets (for `release.yml` only)

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `APPLE_DEVELOPER_ID_CERTIFICATE` | Base64-encoded `.p12` Developer ID Application certificate |
| `APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD` | Password for the `.p12` export |
| `KEYCHAIN_PASSWORD` | Arbitrary password for the CI runner's temporary keychain |
| `NOTARYTOOL_APPLE_ID` | Apple ID email for notarization |
| `NOTARYTOOL_TEAM_ID` | Apple Developer Team ID (10-char alphanumeric) |
| `NOTARYTOOL_PASSWORD` | App-specific password from [appleid.apple.com](https://appleid.apple.com/account/manage) |

## License

MIT
