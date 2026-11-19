# The app updates itself into a versioned user directory

Status: accepted

The application must take App updates by itself on both machines, unattended. Each release is a PyInstaller onedir that the service installs into a user-owned `versions/<v>/` directory, then switches a `current` pointer. If the new version does not report ready within 60 s, the service switches back. Releases come from a private GitHub repo, built by GitHub Actions on a `v*` tag.

## Considered Options

- **pacman package on Linux (PKGBUILD):** rejected. It needs root, so the app cannot update itself overnight.
- **Manual updates, the window only notifies:** rejected. The operator would have to act after every release.
- **Self-hosted Forgejo as the source:** rejected. It depends on the home domain and server.

## Consequences

- No root on Linux and no installer on Windows. The current version and one previous are kept, and rollback is a pointer switch.
- Data formats stay backward-compatible unless a release declares an explicit migration.
- An App update rebuilds the farmer patch only when the farmer hash changes.
