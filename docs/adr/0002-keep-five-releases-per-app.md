# Keep five releases per app, no debug refs, no static deltas

GitHub Pages is advised to stay under about 1 GB. Measured bundles are 10–25 MB, so five apps releasing a few times a month would pass that within months if every release stayed.

- **Retention**: the five newest releases of each app are published. Older ones leave the repository but remain as assets on the app's GitHub Releases page, so any version can still be installed from its `.flatpak` file. A release outside the window cannot be installed from this remote, and a user far behind pulls the latest objects instead of a delta.
- **No debug refs**: the `.Debug` extension of an app can be several times the size of the app itself. Only the app ref in the release bundle is published.
- **No static deltas**: Rust and Go binaries change almost entirely between releases, so deltas would roughly double the size for little saving. Updates still download only the objects that changed.

Five releases per app keeps the repository in the low hundreds of megabytes. `releases_per_app` in `config.toml` changes the window.
