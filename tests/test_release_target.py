import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ci import release_target


class ReleaseTargetTests(unittest.TestCase):
    def resolve(self, event, ref, version="", publish="false", refs=None):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env = Path(directory) / "env"
            inputs = {
                "GITHUB_EVENT_NAME": event,
                "GITHUB_REF": ref,
                "GITHUB_SHA": "head-sha",
                "MANUAL_VERSION": version,
                "PUBLISH_RELEASE": publish,
                "GITHUB_OUTPUT": str(output),
                "GITHUB_ENV": str(env),
            }
            with patch.dict(os.environ, inputs), patch.object(
                release_target, "find_tag_refs", return_value=refs or {}
            ) as find_refs:
                release_target.main()
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual(env.read_text().strip(), f"APP_VERSION={values['version']}")
            return values, find_refs.call_count

    def test_manual_release_uses_new_tag_and_pins_current_commit(self):
        values, lookups = self.resolve("workflow_dispatch", "refs/heads/main", " v1.2.0 ", "true")
        self.assertEqual(values, {"version": "1.2.0", "tag": "v1.2.0", "commit": "head-sha"})
        self.assertEqual(lookups, 1)

    def test_manual_release_reuses_existing_unprefixed_tag(self):
        values, _ = self.resolve(
            "workflow_dispatch", "refs/heads/main", "1.1.0", "true",
            {"refs/tags/1.1.0": "1.1.0-source"},
        )
        self.assertEqual(values, {"version": "1.1.0", "tag": "1.1.0", "commit": "1.1.0-source"})

    def test_existing_annotated_tag_uses_the_peeled_commit(self):
        refs = {"refs/tags/v1.1.0": "tag-object", "refs/tags/v1.1.0^{}": "source-sha"}
        self.assertEqual(release_target.tagged_target("1.1.0", refs, "head"), ("v1.1.0", "source-sha"))

    def test_manual_preview_preserves_selected_branch_and_has_no_release_tag(self):
        values, lookups = self.resolve("workflow_dispatch", "refs/heads/feature", "1.2.0")
        self.assertEqual(values, {"version": "1.2.0", "tag": "", "commit": "head-sha"})
        self.assertEqual(lookups, 0)

    def test_manual_publish_rejects_invalid_version_and_non_main_branch(self):
        with self.assertRaisesRegex(ValueError, "Invalid version"):
            self.resolve("workflow_dispatch", "refs/heads/main", "1.", "true")
        with self.assertRaisesRegex(ValueError, "Select main"):
            self.resolve("workflow_dispatch", "refs/heads/feature", "1.2.0", "true")

    def test_tag_push_still_targets_the_pushed_tag(self):
        values, lookups = self.resolve("push", "refs/tags/v1.3.0")
        self.assertEqual(values, {"version": "1.3.0", "tag": "v1.3.0", "commit": "head-sha"})
        self.assertEqual(lookups, 0)

    def test_pull_requests_still_build_a_preview(self):
        values, lookups = self.resolve("pull_request", "refs/pull/7/merge")
        self.assertEqual(values, {"version": "0.0.0", "tag": "", "commit": "head-sha"})
        self.assertEqual(lookups, 0)
