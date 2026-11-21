# 13: Keep any legendary not yet in storage

**What to build:** Besides the wishlist, the operator wants a remembered window switch "Keep every legendary I don't own yet". When on, an offered legendary is kept if no stored item has the same id (the same "owned" rule the wishlist uses), whether or not it is on the wishlist. Wishlist items still come first when keep slots are limited; paid keeps after a defeat still respect `keep_max_pct`; full storage still uses the room-making rule that never removes worn, legendary, unique, potential or trait items. The switch travels in the session settings like the other window settings and is off by default.

**Blocked by:** 12 (same files).

**Status:** ready-for-agent

- [ ] Window switch, remembered, carried by Start/Resume into `farmer.cfg`; covered by GUI and service tests.
- [ ] With the switch on, an offered unowned legendary not on the wishlist is kept; an owned one is not; wishlist items win when slots are short; covered by a verify judge on the existing deterministic `wishlist-keep` offer and a real run.
- [ ] Static checks, mypy (linux, win32), pytest suites pass.
