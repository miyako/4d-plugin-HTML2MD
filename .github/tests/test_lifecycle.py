import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import release
import source_version as source


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def git(path, *args):
    location = ["--git-dir", str(path)] if path.name.endswith(".git") else ["-C", str(path)]
    return subprocess.run(
        ["git", *location, *args], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def entry(tag="v9.8.7", draft=False):
    return {"id": 42, "tag_name": tag, "draft": draft, "prerelease": False}


class AvailabilityTests(unittest.TestCase):
    def test_paginated_drafts_and_published_collisions(self):
        for draft in (False, True):
            with self.subTest(draft=draft), \
                    patch.object(release, "remote_ref", return_value=None), \
                    patch.object(release, "api", side_effect=[
                        [entry()] * 100, [entry("v1.2.3", draft)]
                    ]) as api:
                with self.assertRaisesRegex(ValueError, "draft or published"):
                    release.available("owner/repo", "v1.2.3")
                self.assertEqual(api.call_args_list[1].args[0],
                                 "repos/owner/repo/releases?per_page=100&page=2")
        with patch.object(release, "remote_ref", return_value=None), \
                patch.object(release, "api", side_effect=[[entry()] * 100, []]) as api:
            release.available("owner/repo", "v1.2.3")
            self.assertEqual(api.call_count, 2)

    def test_all_pages_fail_closed(self):
        errors = [
            *(subprocess.CalledProcessError(1, ["gh", "api", str(status)])
              for status in (401, 403, 404, 500)),
            OSError("network"), json.JSONDecodeError("bad", "?", 0),
        ]
        malformed = [{}, None, "[]", [None], [{}], [dict(entry(), id=True)],
                     [dict(entry(), id=0)], [dict(entry(), tag_name=None)],
                     [dict(entry(), tag_name="")], [dict(entry(), draft="false")],
                     [dict(entry(), prerelease=None)], [entry()] * 101]
        for page in (1, 2):
            for response in errors + malformed:
                with self.subTest(page=page, response=response), \
                        patch.object(release, "remote_ref", return_value=None), \
                        patch.object(release, "api", side_effect=(
                            [[entry()] * 100] * (page - 1) + [response])):
                    with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
                        release.available("owner/repo", "v1.2.3")

    def test_remote_response_validation(self):
        for output in ("invalid\trefs/tags/v1.2.3", "a" * 40,
                       "a" * 40 + "\trefs/tags/wrong",
                       ("a" * 40 + "\trefs/tags/v1.2.3\n") * 2):
            with self.subTest(output=output), patch.object(release, "run", return_value=output):
                with self.assertRaises(ValueError):
                    release.remote_ref("refs/tags/v1.2.3")
        with patch.object(release, "remote_ref", return_value="a" * 40), \
                patch.object(release, "api") as api:
            with self.assertRaises(ValueError):
                release.available("o/r", "v1.2.3")
            api.assert_not_called()
        with patch.object(release, "run", side_effect=OSError("network")):
            with self.assertRaises(OSError):
                release.available("o/r", "v1.2.3")

    def test_explicit_transport_no_retry(self):
        with patch.object(release, "run", return_value="[]") as run:
            release.api("repos/o/r/releases?per_page=100&page=2")
            self.assertEqual(run.call_args.args, ("gh", "api", "--method", "GET",
                             "repos/o/r/releases?per_page=100&page=2"))
        with patch.object(release, "run", return_value='{"id":7}') as run:
            payload = {"tag_name": "v1.2.3", "draft": False}
            release.api("repos/o/r/releases", payload)
            self.assertIn("POST", run.call_args.args)
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        with patch.object(release, "run", return_value='{"id":8}') as run:
            asset = Path("HTML2MD-1.2.3.zip")
            release.api("https://uploads.github.com/repos/o/r/releases/123/assets", asset=asset)
            self.assertEqual(run.call_args.args, (
                "gh", "api", "--method", "POST",
                "https://uploads.github.com/repos/o/r/releases/123/assets",
                "--header", "Content-Type: application/octet-stream", "--input", str(asset)))
        with patch.object(release, "run", side_effect=subprocess.CalledProcessError(1, "gh")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                release.api("repos/o/r/releases")
            self.assertEqual(run.call_count, 1)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        self.peer = self.root / "peer"
        git(self.root, "init", "--bare", str(self.remote))
        git(self.root, "init", "-b", "selected", str(self.local))
        for key, value in (("user.name", "Lifecycle Test"), ("user.email", "test@example.invalid"),
                           ("push.followTags", "true")):
            git(self.local, "config", key, value)
        git(self.local, "commit", "--allow-empty", "-m", "ancestor")
        self.ancestor = git(self.local, "rev-parse", "HEAD")
        for path in source.SOURCE_PATHS:
            (self.local / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, self.local / path)
        shutil.copytree(ROOT / ".github/scripts", self.local / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        git(self.local, "add", ".")
        git(self.local, "commit", "-m", "fixture")
        git(self.local, "remote", "add", "origin", str(self.remote))
        git(self.local, "push", "origin", "HEAD:refs/heads/selected")
        self.sha = git(self.local, "rev-parse", "HEAD")
        self.version = source.read(self.local)
        self.tag = f"v{self.version}"
        self.published = None
        self.uploaded = []
        git(self.root, "clone", "--branch", "selected", str(self.remote), str(self.peer))
        git(self.peer, "config", "user.name", "Peer")
        git(self.peer, "config", "user.email", "peer@example.invalid")
        self.enter = cwd(self.local)
        self.enter.__enter__()
        self.addCleanup(self.enter.__exit__, None, None, None)
        self.file_patch = patch.object(release, "__file__", str(self.local / ".github/scripts/release.py"))
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)

    def advance_peer(self):
        git(self.peer, "commit", "--allow-empty", "-m", "peer")
        git(self.peer, "push", "origin", "HEAD:refs/heads/selected")
        return git(self.peer, "rev-parse", "HEAD")

    def test_source_only_explicit_branch_no_follow_tags(self):
        git(self.local, "tag", "-a", "unrelated-annotated", "-m", "must not follow")
        git(self.remote, "update-ref", "refs/heads/other", self.sha)
        release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(git(self.local, "rev-parse", "HEAD^"), self.sha)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/selected"),
                         git(self.local, "rev-parse", "HEAD"))
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/other"), self.sha)
        self.assertEqual(git(self.remote, "tag", "--list"), "")
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        changed = git(self.local, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        self.assertTrue(set(changed.splitlines()) <= set(map(str, source.SOURCE_PATHS)))
        self.assertIn("VERSION", changed.splitlines())

    def test_cli_no_bytecode(self):
        env = os.environ.copy()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        subprocess.run(
            [sys.executable, ".github/scripts/release.py", "bump", "--sha", self.sha,
             "--branch", "selected", "--mode", "patch"],
            env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_preparation_races(self):
        real_bump = release.bump

        def concurrent_bump(mode):
            result = real_bump(mode)
            self.advance_peer()
            return result

        with patch.object(release, "bump", side_effect=concurrent_bump):
            with self.assertRaisesRegex(ValueError, "moved during"):
                release.bump_branch(self.sha, "selected", "minor")
        self.assertEqual(release.remote_ref("refs/heads/selected"),
                         git(self.peer, "rev-parse", "HEAD"))

    def test_initial_advance(self):
        self.advance_peer()
        with self.assertRaisesRegex(ValueError, "moved"):
            release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), self.sha)

    def late_race(self, kind):
        real_run = release.run
        expected = None
        checks = 0
        pushes = 0

        def concurrent_push(*args, **kwargs):
            nonlocal expected, checks, pushes
            if args[:2] == ("git", "ls-remote"):
                checks += 1
            # Exactly after the final ls-remote and before receive-pack advertisement.
            if "push" in args:
                self.assertEqual(checks, 2)
                pushes += 1
                if kind == "rewind":
                    expected = self.ancestor
                    git(self.remote, "update-ref", "refs/heads/selected", expected)
                elif kind == "delete":
                    git(self.remote, "update-ref", "-d", "refs/heads/selected")
                elif kind == "advance":
                    expected = self.advance_peer()
                elif kind == "same-result":
                    expected = git(self.local, "rev-parse", "HEAD")
                    git(self.remote, "fetch", "--no-tags", str(self.local), "HEAD")
                    git(self.remote, "update-ref", "refs/heads/selected", expected)
            return real_run(*args, **kwargs)

        with patch.object(release, "run", side_effect=concurrent_push):
            with self.assertRaises(subprocess.CalledProcessError):
                release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(pushes, 1)
        self.assertEqual(release.remote_ref("refs/heads/selected"), expected)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_late_rewind(self):
        self.late_race("rewind")

    def test_late_delete(self):
        self.late_race("delete")

    def test_late_advance(self):
        self.late_race("advance")

    def test_late_same_result(self):
        self.late_race("same-result")

    def test_guard_missing_nonexecutable_and_recheck(self):
        guard = self.local / ".github/scripts/bump-hooks/pre-push"
        guard.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "guard"):
            release.bump_branch(self.sha, "selected", "patch")
        guard.unlink()
        with self.assertRaisesRegex(ValueError, "guard"):
            release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), self.sha)

    def test_guard_disappears_after_final_remote_check(self):
        real_remote = release.remote_ref
        checks = 0

        def remove_guard(ref):
            nonlocal checks
            result = real_remote(ref)
            checks += 1
            if checks == 2:
                (self.local / ".github/scripts/bump-hooks/pre-push").unlink()
            return result

        with patch.object(release, "remote_ref", side_effect=remove_guard), \
                patch.object(release, "require_guard", wraps=release.require_guard) as guard:
            with self.assertRaises(ValueError):
                release.bump_branch(self.sha, "selected", "patch")
            self.assertEqual(guard.call_count, 1 if checks < 2 else 2)
        self.assertEqual(real_remote("refs/heads/selected"), self.sha)

    def test_guard_exact_tuple_parent_head_and_count(self):
        guard = self.local / ".github/scripts/bump-hooks/pre-push"
        git(self.local, "commit", "--allow-empty", "-m", "direct child")
        new = git(self.local, "rev-parse", "HEAD")
        env = {**os.environ, "BUMP_EXPECTED_SHA": self.sha,
               "BUMP_EXPECTED_REF": "refs/heads/selected", "BUMP_NEW_SHA": new}
        valid = f"{new} {new} refs/heads/selected {self.sha}\n"
        rows = [valid, valid.replace("refs/heads/selected", "refs/heads/wrong"),
                valid.replace(new, "HEAD", 1), valid.replace(self.sha, self.ancestor),
                f"{new} {self.ancestor} refs/heads/selected {self.sha}\n", valid * 2, ""]
        for i, row in enumerate(rows):
            result = subprocess.run([str(guard)], input=row, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode == 0, i == 0, result.stderr)
        git(self.local, "commit", "--allow-empty", "-m", "not direct")
        result = subprocess.run([str(guard)], input=valid, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        result = subprocess.run([str(guard)], input=valid, env={}, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_sha_branch_and_dirty_source(self):
        for sha in ("selected", "a" * 40, "a" * 39, "a" * 41):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                release.selected_sha(sha)
        with self.assertRaises(subprocess.CalledProcessError):
            release.bump_branch(self.sha, "invalid..branch", "patch")
        (self.local / "dirty").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "clean checkout"):
            release.bump_branch(self.sha, "selected", "patch")

    def assets(self):
        paths = [Path(f"HTML2MD-{self.version}.{ext}") for ext in ("zip", "dmg")]
        for asset in paths:
            asset.write_bytes(b"fixture asset")
        return paths

    def publication_api(self, calls, fail=None, race=None, malformed=None):
        def api(endpoint, payload=None, asset=None):
            calls.append((endpoint, payload, asset))
            if "/releases?" in endpoint:
                return []
            if endpoint.endswith("/git/refs"):
                if race:
                    git(self.remote, "update-ref", f"refs/tags/{self.tag}", race)
                # Atomic bare Git models create-only POST refs, including same-SHA rejection.
                git(self.remote, "update-ref", payload["ref"], payload["sha"], "0" * 40)
                return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
            if endpoint.endswith("/releases"):
                if fail == "release":
                    raise subprocess.CalledProcessError(1, ["gh", "api"])
                self.published = {"id": 123, "tag_name": self.tag, "draft": False, "prerelease": False}
                return {} if malformed == "release" else self.published
            if asset is not None:
                if fail == asset.suffix:
                    raise subprocess.CalledProcessError(1, ["gh", "api"])
                self.uploaded.append(asset.name)
                return {} if malformed == "upload" else {
                    "id": 456, "name": asset.name, "size": asset.stat().st_size, "state": "uploaded"}
            raise AssertionError(endpoint)
        return api

    def test_create_only_selected_sha_notes_and_new_release_id(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)):
            release.publish(self.sha, self.assets())
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)
        self.assertEqual(calls[2][1], {
            "tag_name": self.tag, "target_commitish": self.sha, "name": self.tag,
            "draft": False, "prerelease": False, "body": ""})
        self.assertEqual(len(calls), 5)
        for endpoint, payload, asset in calls[3:]:
            self.assertIn("/releases/123/assets?name=", endpoint)
            self.assertIsNone(payload)
            self.assertIsNotNone(asset)

    def tag_race(self, sha):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls, race=sha)):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 2)
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), sha)
        self.assertIsNone(self.published)

    def test_same_sha_tag_race(self):
        self.tag_race(self.sha)

    def test_different_sha_tag_race(self):
        self.tag_race(self.advance_peer())

    def retained_state(self, fail=None, malformed=None):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(
                    calls, fail=fail, malformed=malformed)):
            with self.assertRaises((subprocess.CalledProcessError, ValueError)):
                release.publish(self.sha, self.assets())
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)
        expected_calls = 3 if fail == "release" or malformed == "release" else (
            4 if fail == ".zip" or malformed == "upload" else 5)
        self.assertEqual(len(calls), expected_calls)
        if fail != "release":
            self.assertEqual(self.published["id"], 123)
        if fail == ".dmg":
            self.assertEqual(self.uploaded, [f"HTML2MD-{self.version}.zip"])

    def test_release_failure_retains_tag(self):
        self.retained_state(fail="release")

    def test_first_asset_failure_retains_release(self):
        self.retained_state(fail=".zip")

    def test_second_asset_failure_retains_first_asset(self):
        self.retained_state(fail=".dmg")

    def test_malformed_release_retains_state(self):
        self.retained_state(malformed="release")

    def test_malformed_upload_retains_state(self):
        self.retained_state(malformed="upload")

    def test_final_recheck_draft_and_later_page_failure(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", return_value=[]):
            release.preflight(self.sha)
        paths = self.assets()
        for replies in ([entry(self.tag, True)], [
                [entry()] * 100, subprocess.CalledProcessError(1, ["gh", "api", "404"])]):
            with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                    patch.object(release, "api", side_effect=(
                        [replies] if isinstance(replies[0], dict) else replies)) as api:
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    release.publish(self.sha, paths)
                self.assertTrue(all("/releases?" in call.args[0] for call in api.call_args_list))
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_remote_verification_blocks_release(self):
        calls = []
        real_remote = release.remote_ref

        def wrong_sha(ref):
            return "a" * 40 if real_remote(ref) else None

        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)), \
                patch.object(release, "remote_ref", side_effect=wrong_sha):
            with self.assertRaisesRegex(ValueError, "exact-SHA verification"):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.published)

    def test_preflight_clean_final_metadata_and_asset_validation(self):
        source.bump("patch")
        with self.assertRaisesRegex(ValueError, "clean source"):
            release.preflight(self.sha)
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api") as api:
            with self.assertRaisesRegex(ValueError, "differs from the selected commit"):
                release.publish(self.sha, self.assets())
            api.assert_not_called()

    def test_missing_empty_or_wrong_assets_stop_before_remote_creation(self):
        paths = self.assets()
        for bad in ([paths[1], paths[0]], [paths[0]], [Path("wrong.zip"), paths[1]]):
            with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                    patch.object(release, "api") as api:
                with self.assertRaisesRegex(ValueError, "Expected release assets"):
                    release.publish(self.sha, bad)
                api.assert_not_called()
        paths[0].write_bytes(b"")
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api") as api:
            with self.assertRaisesRegex(ValueError, "Missing or empty"):
                release.publish(self.sha, paths)
            api.assert_not_called()
        paths[0].unlink()
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api") as api:
            with self.assertRaisesRegex(ValueError, "Missing or empty"):
                release.publish(self.sha, paths)
            api.assert_not_called()
        self.assertEqual(git(self.remote, "tag", "--list"), "")


class WorkflowTests(unittest.TestCase):
    def test_dispatch_immutable_checkouts_and_native_gates(self):
        build = (ROOT / ".github/workflows/release.yml").read_text()
        bump = (ROOT / ".github/workflows/bump-version.yml").read_text()
        self.assertTrue(build.startswith("name: Build\n"))
        self.assertIn("on:\n  workflow_dispatch:\n", build)
        self.assertNotIn("inputs:", build)
        self.assertNotIn("\n  push:", build)
        self.assertEqual(build.count("uses: actions/checkout@v4"), 3)
        self.assertEqual(build.count("ref: ${{ github.sha }}"), 3)
        self.assertIn("group: release-publication\n  cancel-in-progress: false", build)
        self.assertNotIn("github.ref", build)
        self.assertIn("ref: ${{ github.sha }}", bump)
        self.assertIn('test "$REF_TYPE" = branch', bump)
        self.assertNotIn("git tag", bump)
        self.assertNotIn("release.yml will pick", bump)
        self.assertLess(build.index("release.py preflight"), build.index("build-windows:"))
        gates = ["build-windows:", "build-macos:", "cmake --build .",
                 "lipo -info", "codesign --verify", 'notarytool submit "$ZIP_PATH"',
                 'notarytool submit "$DMG_PATH"', 'stapler staple "$DMG_PATH"']
        for gate in gates:
            self.assertLess(build.index(gate), build.index("release.py publish"))
        self.assertIn("needs: [version, build-windows]", build)
        for secret in ("APPLE_DEVELOPER_ID_CERTIFICATE", "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD",
                       "KEYCHAIN_PASSWORD", "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID",
                       "NOTARYTOOL_PASSWORD"):
            self.assertIn(f"secrets.{secret}", build)
        for preserved in ('MACOS_DEPLOYMENT_TARGET: \'10.13\'', '-A x64',
                          'CMAKE_OSX_ARCHITECTURES="arm64;x86_64"', "windows-binaries",
                          'ditto -c -k --keepParent', 'hdiutil create -format UDBZ'):
            self.assertIn(preserved, build)

    def test_no_destructive_publication_or_automatic_build(self):
        text = (ROOT / ".github/scripts/release.py").read_text()
        for forbidden in ('"DELETE"', '"PATCH"', "--clobber", "gh release create",
                          "action-gh-release", "--force", "--force-with-lease"):
            self.assertNotIn(forbidden, text)
        self.assertIn('"push.followTags=false"', text)
        self.assertIn('"--no-follow-tags"', text)
        self.assertEqual(text.count("require_guard(guard)"), 3)
        test = (ROOT / ".github/workflows/test.yml").read_text()
        self.assertIn("name: Build and Test", test)
        self.assertIn("push:\n    tags:\n      - '*'", test)


if __name__ == "__main__":
    unittest.main()
