#!/usr/bin/env python3
"""Builds the static Flatpak repository site from the apps' GitHub release bundles.

plan      list each app's newest releases and decide whether the site is out of date
fetch     download the bundles named in the plan
assemble  import them into a signed OSTree repository and write the site around it
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

RUNTIME_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"
RELEASE_LIST_LIMIT = 50


def load_config(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def select_releases(releases: list[dict], limit: int) -> list[dict]:
    """The newest `limit` published, non-prerelease releases, newest first."""
    published = [r for r in releases if not r["isDraft"] and not r["isPrerelease"]]
    published.sort(key=lambda r: r["publishedAt"], reverse=True)
    return published[:limit]


def pick_asset(assets: list[dict]) -> dict | None:
    """The release's Flatpak bundle; development builds are not published."""
    for asset in assets:
        name = asset["name"]
        if name.endswith(".flatpak") and ".Devel" not in name:
            return asset
    return None


def sidecar_checksum(assets: list[dict], bundle_name: str) -> str | None:
    wanted = f"{bundle_name}.sha256"
    return wanted if any(a["name"] == wanted for a in assets) else None


def repo_url(config: dict) -> str:
    return config["repo"]["url"].rstrip("/") + "/repo/"


def render_flatpakrepo(config: dict, gpg_key: str) -> str:
    repo = config["repo"]
    return (
        "[Flatpak Repo]\n"
        f"Title={repo['title']}\n"
        f"Url={repo_url(config)}\n"
        f"Homepage={repo['homepage']}\n"
        f"Comment={repo['comment']}\n"
        f"GPGKey={gpg_key}\n"
    )


def render_flatpakref(config: dict, app: dict, branch: str, gpg_key: str) -> str:
    return (
        "[Flatpak Ref]\n"
        f"Title={app['name']}\n"
        f"Name={app['id']}\n"
        f"Branch={branch}\n"
        f"Url={repo_url(config)}\n"
        f"SuggestRemoteName={config['repo']['name']}\n"
        "IsRuntime=false\n"
        f"RuntimeRepo={RUNTIME_REPO}\n"
        f"GPGKey={gpg_key}\n"
    )


def render_index(config: dict, rows: list[dict]) -> str:
    repo = config["repo"]
    base = repo["url"].rstrip("/")
    name = repo["name"]
    items = "\n".join(
        f"      <li><strong>{html.escape(row['name'])}</strong> — "
        f"{html.escape(row['summary'])} "
        f"(<a href=\"apps/{html.escape(row['id'])}.flatpakref\">install file</a>, "
        f"<code>flatpak install {html.escape(name)} {html.escape(row['id'])}</code>)</li>"
        for row in rows
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(repo['title'])}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.5; }}
      pre {{ background: #8881; padding: 0.75rem; overflow-x: auto; }}
    </style>
  </head>
  <body>
    <h1>{html.escape(repo['title'])}</h1>
    <p>{html.escape(repo['comment'])}.</p>
    <h2>Add the repository</h2>
    <pre>flatpak remote-add --user --if-not-exists {html.escape(name)} {html.escape(base)}/{html.escape(name)}.flatpakrepo</pre>
    <h2>Apps</h2>
    <ul>
{items}
    </ul>
  </body>
</html>
"""


def run(*cmd: str, env: dict | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=capture,
        env={**os.environ, **(env or {})},
    )
    return result.stdout if capture else ""


def gh_json(*args: str):
    return json.loads(run("gh", *args))


def plan(config: dict, previous_state_url: str | None, out: Path) -> bool:
    """Writes plan.json under `out` and returns whether the published site is stale."""
    limit = config["retention"]["releases_per_app"]
    state: dict[str, list[dict]] = {}
    for app in config["apps"]:
        try:
            releases = gh_json(
                "release", "list", "--repo", app["repo"],
                "--limit", str(RELEASE_LIST_LIMIT),
                "--json", "tagName,isDraft,isPrerelease,publishedAt",
            )
        except subprocess.CalledProcessError as error:
            print(f"warning: no releases for {app['repo']}: {error.stderr.strip()}", file=sys.stderr)
            state[app["id"]] = []
            continue

        entries = []
        for release in select_releases(releases, limit):
            assets = gh_json(
                "release", "view", release["tagName"], "--repo", app["repo"],
                "--json", "assets",
            )["assets"]
            bundle = pick_asset(assets)
            if bundle is None:
                print(f"warning: {app['repo']} {release['tagName']} has no Flatpak bundle", file=sys.stderr)
                continue
            entries.append({
                "tag": release["tagName"],
                "published": release["publishedAt"],
                "asset": bundle["name"],
                "size": bundle["size"],
                "checksum_asset": sidecar_checksum(assets, bundle["name"]),
            })
        state[app["id"]] = entries

    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state != fetch_previous_state(previous_state_url)


def fetch_previous_state(url: str | None) -> dict | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(config: dict, out: Path) -> None:
    state = json.loads((out / "plan.json").read_text())
    apps = {app["id"]: app for app in config["apps"]}
    for app_id, entries in state.items():
        app = apps[app_id]
        for entry in entries:
            target = out / "bundles" / app_id / entry["tag"]
            target.mkdir(parents=True, exist_ok=True)
            patterns = [entry["asset"]] + ([entry["checksum_asset"]] if entry["checksum_asset"] else [])
            args = ["release", "download", entry["tag"], "--repo", app["repo"], "--dir", str(target), "--clobber"]
            for pattern in patterns:
                args += ["--pattern", pattern]
            run("gh", *args)

            bundle = target / entry["asset"]
            if entry["checksum_asset"]:
                expected = (target / entry["checksum_asset"]).read_text().split()[0]
                if sha256_of(bundle) != expected:
                    raise SystemExit(f"checksum mismatch for {app['repo']} {entry['tag']}")
            if app.get("verify_attestation"):
                run("gh", "attestation", "verify", str(bundle), "--repo", app["repo"])


def default_key_id(gpg_home: Path) -> str:
    listing = run("gpg", "--homedir", str(gpg_home), "--list-secret-keys", "--with-colons")
    for line in listing.splitlines():
        if line.startswith("fpr:"):
            return line.split(":")[9]
    raise SystemExit("no secret GPG key found")


def export_public_key(gpg_home: Path, key_id: str) -> str:
    key = subprocess.run(
        ["gpg", "--homedir", str(gpg_home), "--export", key_id],
        check=True,
        capture_output=True,
    ).stdout
    return base64.b64encode(key).decode()


def app_refs(repo_dir: Path) -> dict[str, str]:
    """Maps app id to branch for every app ref in the repository."""
    refs = run("ostree", f"--repo={repo_dir}", "refs").split()
    found = {}
    for ref in refs:
        parts = ref.split("/")
        if len(parts) == 4 and parts[0] == "app":
            found[parts[1]] = parts[3]
    return found


def assemble(config: dict, out: Path, gpg_home: Path, key_id: str | None) -> None:
    state = json.loads((out / "plan.json").read_text())
    key_id = key_id or default_key_id(gpg_home)
    gpg_args = [f"--gpg-sign={key_id}", f"--gpg-homedir={gpg_home}"]
    site = out / "site"
    repo_dir = site / "repo"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)

    run("ostree", f"--repo={repo_dir}", "init", "--mode=archive-z2")
    for app_id, entries in state.items():
        # Oldest first so each release becomes the parent of the next one.
        for entry in sorted(entries, key=lambda e: e["published"]):
            bundle = out / "bundles" / app_id / entry["tag"] / entry["asset"]
            run("flatpak", "build-import-bundle", *gpg_args, str(repo_dir), str(bundle))

    retention = config["retention"]["releases_per_app"]
    repo = config["repo"]
    run(
        "flatpak", "build-update-repo", *gpg_args,
        f"--title={repo['title']}", f"--comment={repo['comment']}",
        f"--homepage={repo['homepage']}",
        "--prune", f"--prune-depth={retention}",
        str(repo_dir),
    )

    gpg_key = export_public_key(gpg_home, key_id)
    branches = app_refs(repo_dir)
    apps_dir = site / "apps"
    apps_dir.mkdir()
    rows = []
    for app in config["apps"]:
        branch = branches.get(app["id"])
        if branch is None:
            continue
        (apps_dir / f"{app['id']}.flatpakref").write_text(render_flatpakref(config, app, branch, gpg_key))
        rows.append(app)

    (site / f"{repo['name']}.flatpakrepo").write_text(render_flatpakrepo(config, gpg_key))
    (site / "index.html").write_text(render_index(config, rows))
    (site / "state.json").write_text((out / "plan.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--out", type=Path, default=Path("build"))
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument(
        "--compare-published",
        action="store_true",
        help="report a change only if the published state.json differs from the plan",
    )
    sub.add_parser("fetch")
    assemble_parser = sub.add_parser("assemble")
    assemble_parser.add_argument("--gpg-homedir", type=Path, required=True)
    assemble_parser.add_argument("--gpg-key")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.command == "plan":
        state_url = config["repo"]["url"].rstrip("/") + "/state.json" if args.compare_published else None
        changed = plan(config, state_url, args.out)
        print(f"changed={'true' if changed else 'false'}")
        if github_output := os.environ.get("GITHUB_OUTPUT"):
            with open(github_output, "a") as handle:
                handle.write(f"changed={'true' if changed else 'false'}\n")
    elif args.command == "fetch":
        fetch(config, args.out)
    else:
        assemble(config, args.out, args.gpg_homedir, args.gpg_key)


if __name__ == "__main__":
    main()
