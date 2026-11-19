# 11: Packaging and release CI

**What to build:** A `v*` tag makes GitHub Actions run the tests on Linux and Windows, build a PyInstaller onedir per OS containing the window and the service, and publish a private release with sha256 files.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] Each onedir starts both entry points on a clean runner without a system Python.
- [ ] The release carries one archive per OS and its sha256.
- [ ] A non-tag push runs tests only.
