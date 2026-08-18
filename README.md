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

This project uses GitHub Actions for automated testing and releases:

| Workflow | Trigger | Purpose |
|---|---|---|
| `test.yml` | Tag push / manual | Build & test on macOS + Windows |
| `bump-version.yml` | Manual | Bump `VERSION`, commit, push tag |
| `release.yml` | `v*.*.*` tag | Build, sign, notarize, GitHub Release |

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
