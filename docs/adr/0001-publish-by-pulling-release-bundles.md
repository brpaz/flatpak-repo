# Publish by pulling each app's release bundle

One repository serves every app, so something has to bring each app's build into it. Two shapes were considered:

- **Push**: each app's release workflow writes into this repository. Every app repository needs a write token for this one, and two apps releasing at once race on the same OSTree repository.
- **Pull**: each app already attaches a `.flatpak` bundle to its GitHub release. This repository reads those releases, imports the bundles, signs the result and deploys it.

Pull is used. Only this repository holds the signing key and Pages access, apps need no cross-repository secret, and the `concurrency` group serialises deployments. A schedule finds new releases without any signal from the apps; a `repository_dispatch` from an app's release workflow is an optional way to publish sooner.

The repository is rebuilt from the selected bundles on every publish instead of being updated in place. The published site is a pure function of the apps' releases and `config.toml`, which keeps the site small (see ADR-0002), makes a failed run harmless, and needs no state kept between runs beyond `state.json` on the site, which lets a run skip the build when nothing changed.
