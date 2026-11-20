# 05: Keep by wishlist

**What to build:** The operator edits a wishlist of legendary items in the window (search by name over the catalog, owned items marked). Start and Resume carry it. At the end screen the farmer keeps an offered item only if it is on the wishlist, not owned (no stored item with the same id), passes the game's keep rules, and the keep is free or its paid cost fits `keep_max_pct`. Full storage uses the existing room-making rule. Skips are logged with a reason and recorded in the run journal. Everything else is cashed in or sold as today. Value-based keep and `auto_keep` are removed; a preset containing `auto_keep` is refused naming the key. The journal and history show kept items.

**Blocked by:** 02, 03.

**Status:** resolved

- [x] The wishlist editor searches the catalog's legendaries, marks owned ones, is disabled without a catalog, and is remembered; covered by GUI tests.
- [x] Start and Resume carry the wishlist into `farmer.cfg`; malformed wishlists are rejected; covered by tests.
- [x] Value-based keep and `auto_keep` are gone; a preset with `auto_keep` is refused naming the key.
- [x] A verify scenario: with an offered item on the wishlist, only that item is added to storage; an owned wishlist item is not kept again; non-wishlist legendaries are cashed in.
- [x] Skipped wishlist items appear in the log and run journal with a reason; kept items appear in the journal and history.
- [x] Static checks and the pytest suite pass.

Spec: [`../spec.md`](../spec.md).
