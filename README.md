# flatpak-repo

A signed Flatpak repository for my apps, served from GitHub Pages. It is rebuilt from the apps' GitHub release bundles, so the apps need no changes beyond attaching a `.flatpak` file to a release.

## Install an app

```bash
flatpak remote-add --user --if-not-exists brunopaz https://brpaz.github.io/flatpak-repo/brunopaz.flatpakrepo
flatpak install brunopaz dev.brunopaz.ResticViewer
```

`flatpak update` then keeps it current. The GNOME runtime comes from Flathub, which the install pulls in on first use.

## How it works

`.github/workflows/publish.yml` runs every six hours, on demand, and when an app sends an `app-released` dispatch:

1. `plan` lists each app's newest releases (`releases_per_app` in `config.toml`) and compares them with the `state.json` already published. Nothing changed means the run stops there.
2. `fetch` downloads each release's bundle, checks its `.sha256` file when one exists, and verifies its build attestation for apps that set `verify_attestation`.
3. `assemble` imports the bundles into a fresh OSTree repository, signs it, and writes the `.flatpakrepo` file, a `.flatpakref` file per app, and an index page.
4. The result is deployed to GitHub Pages.

Design decisions are in [`docs/adr`](docs/adr).

## Set up

1. Create the GitHub repository and push this one to it.
2. In **Settings → Pages**, set the source to **GitHub Actions**.
3. Create the signing key and store it as a secret (the key has no passphrase because CI uses it unattended):
   ```bash
   scripts/generate-key.sh
   gh secret set GPG_PRIVATE_KEY < flatpak-repo-signing.key
   shred -u flatpak-repo-signing.key
   ```
4. Run the **Publish** workflow once with **force** ticked.

The public key is derived from the secret on every run and embedded in the `.flatpakrepo` and `.flatpakref` files. Back the private key up somewhere safe: losing it means users must re-add the remote with a new key.

## Use your own domain

Users store the repository URL when they add the remote, so switch domains before sharing it widely.

1. Point a `CNAME` record for the domain at `<user>.github.io`.
2. Set the custom domain in **Settings → Pages** and enable HTTPS.
3. Set `repo.url` in `config.toml` to the new URL and push. The next publish rewrites the `.flatpakrepo` and `.flatpakref` files.

Anyone who already added the remote keeps the old URL; they run `flatpak remote-modify --url=<new>/repo/ brunopaz` or re-add it.

## Add an app

Add an `[[apps]]` entry to `config.toml` with the Flatpak app ID, display name, summary and `owner/repo`. The app's releases need a `*.flatpak` asset that does not contain `.Devel`. A `<bundle>.flatpak.sha256` asset next to it is verified when present. Set `verify_attestation = true` for apps whose releases carry a build provenance attestation; their releases without one are left out of the repository.

An app whose repository has no releases yet is skipped with a warning.

## Publish sooner

Add a step to an app's release workflow (needs a token with permission to dispatch to this repository):

```yaml
- name: Publish to the Flatpak repository
  env:
    GH_TOKEN: ${{ secrets.FLATPAK_REPO_TOKEN }}
  run: gh api repos/brpaz/flatpak-repo/dispatches -f event_type=app-released
```

## Develop

```bash
task test        # unit tests
task plan        # list what would be published (needs the gh CLI logged in)
```

`scripts/publish.py assemble` needs `flatpak`, `ostree` and `gpg`.
