# 08: `hell-rotation` strategy: endless until the final boss

**What to build:** A strategy preset `hell-rotation` for the operator's Hell meta (Assassin Cross, fixed difficulty 30, all oaths at top rank = 37 points, all locations in turn). In the game's endless mode a run continues after each MVP until the final boss arrives around game minute 41; killing it ends the run as a victory (the end screen offers 3 free keeps "for beating the MVP"), dying ends it as a defeat. The preset therefore keeps endless on with no endless time or MVP cap, and a safety cap of 50 game minutes per run. Objective crumbs, like `crumbs`. The farmer must treat a run the game ends after the final boss as a victory, so settlement, the 3 free wishlist keeps and the run journal record a win, never a timeout or defeat.

**Blocked by:** 07.

**Status:** ready-for-agent

- [ ] `hell-rotation` is a selectable strategy preset: objective crumbs, endless on, no endless minute/MVP cap, `run_minutes` 50; its description in the window reads as a strategy.
- [ ] A run that the game ends after the final boss is recorded as a victory: status/journal `victory: true`, free keep slots, not `run_timeout`.
- [ ] A real verify scenario on the sandbox profile with Assassin Cross, all locations in turn, fixed difficulty 30 and all oaths at top rank (37 points) completes one full run to the final boss and judges: victory, oath points 37, the run's location is the first unlocked location, no timeout. If the sandbox character dies instead, report the death time and cause from the log rather than weakening the judge.
- [ ] Static checks, mypy (Linux and Windows targets as in `.githooks/pre-push`), the pytest suites pass.

Spec: [`../spec.md`](../spec.md).
