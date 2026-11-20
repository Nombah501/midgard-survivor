# 02: Catalog published from the operator's profile

**What to build:** When the farmer starts the game it writes a catalog into the profile: unlocked locations with display names and current difficulty range, the maximum difficulty, all oaths with names, ranks, rank descriptions and point costs, all legendary items with ids and names, and the ids of owned items. Names come from the game's own translation. The smoke run after a farmer patch rebuild runs on a copy of the operator's profile; the app publishes that catalog as the latest one. The window shows when the catalog was last refreshed, or that none exists yet.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The catalog is written atomically before the first run of every game start, including the smoke run.
- [ ] After a successful smoke run the app publishes the sandbox catalog as the latest catalog; covered by the smoke/game-update tests with the fake game writing a fixture catalog.
- [ ] The app reads the latest catalog from the real profile or the published copy, whichever is newer.
- [ ] The AFK screen shows the catalog refresh time, or that no catalog exists; covered by a GUI test.
- [ ] A verify scenario checks a real game start writes a catalog listing the profile's unlocked locations, oaths and legendaries.
- [ ] Static checks and the pytest suite pass.

Spec: [`../spec.md`](../spec.md).
