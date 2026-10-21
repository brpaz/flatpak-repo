import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import publish  # noqa: E402

CONFIG = {
    "repo": {
        "name": "acme",
        "title": "Acme apps",
        "comment": "Apps by Acme",
        "homepage": "https://example.com",
        "url": "https://acme.github.io/flatpaks/",
    }
}
APP = {"id": "com.acme.Tool", "name": "Tool", "summary": "A tool"}


def release(tag, published, draft=False, prerelease=False):
    return {"tagName": tag, "publishedAt": published, "isDraft": draft, "isPrerelease": prerelease}


class SelectReleasesTest(unittest.TestCase):
    def test_keeps_the_newest_published_releases(self):
        releases = [
            release("v1", "2026-01-01T00:00:00Z"),
            release("v3", "2026-03-01T00:00:00Z"),
            release("v2", "2026-02-01T00:00:00Z"),
            release("v4-draft", "2026-04-01T00:00:00Z", draft=True),
            release("v5-rc", "2026-05-01T00:00:00Z", prerelease=True),
        ]

        tags = [r["tagName"] for r in publish.select_releases(releases, 2)]

        self.assertEqual(tags, ["v3", "v2"])


class PickAssetTest(unittest.TestCase):
    def test_skips_development_builds_and_other_files(self):
        assets = [
            {"name": "tool.deb"},
            {"name": "com.acme.Tool.Devel.flatpak"},
            {"name": "com.acme.Tool-1.0-x86_64.flatpak"},
        ]

        self.assertEqual(publish.pick_asset(assets)["name"], "com.acme.Tool-1.0-x86_64.flatpak")

    def test_none_without_a_release_bundle(self):
        self.assertIsNone(publish.pick_asset([{"name": "tool.deb"}]))

    def test_finds_the_checksum_sidecar_only_when_present(self):
        assets = [{"name": "a.flatpak"}, {"name": "a.flatpak.sha256"}]

        self.assertEqual(publish.sidecar_checksum(assets, "a.flatpak"), "a.flatpak.sha256")
        self.assertIsNone(publish.sidecar_checksum(assets[:1], "a.flatpak"))


class RepoUrlTest(unittest.TestCase):
    def test_repo_url_ends_in_the_repo_directory(self):
        self.assertEqual(publish.repo_url(CONFIG), "https://acme.github.io/flatpaks/repo/")


class RenderTest(unittest.TestCase):
    def test_flatpakrepo_points_at_the_repo_and_carries_the_key(self):
        text = publish.render_flatpakrepo(CONFIG, "KEY")

        self.assertIn("Url=https://acme.github.io/flatpaks/repo/", text)
        self.assertIn("GPGKey=KEY", text)
        self.assertIn("Title=Acme apps", text)

    def test_flatpakref_names_the_app_branch_and_runtime_remote(self):
        text = publish.render_flatpakref(CONFIG, APP, "stable", "KEY")

        self.assertIn("Name=com.acme.Tool", text)
        self.assertIn("Branch=stable", text)
        self.assertIn("SuggestRemoteName=acme", text)
        self.assertIn(f"RuntimeRepo={publish.RUNTIME_REPO}", text)

    def test_index_lists_the_apps_and_escapes_text(self):
        page = publish.render_index(CONFIG, [{**APP, "summary": "A <b>tool</b>"}])

        self.assertIn("flatpak remote-add --user --if-not-exists acme https://acme.github.io/flatpaks/acme.flatpakrepo", page)
        self.assertIn("flatpak install acme com.acme.Tool", page)
        self.assertIn("A &lt;b&gt;tool&lt;/b&gt;", page)


if __name__ == "__main__":
    unittest.main()
