# 04: Oaths chosen in the window

**What to build:** First verify the oath facts in the spec's Further Notes against the current official patch. Then the window shows an oath panel (a rank per oath, with the points total) that is active only when the difficulty is a fixed 30. Start and Resume carry the oath ranks; the farmer hands them to the game per run through the game's one-run oath override and never writes the profile's own oath set. An unknown oath, a rank it does not have, or oaths with any difficulty other than 30 end the session as a failure naming the field. Status and history show the oath points of each run.

**Blocked by:** 03.

**Status:** resolved

- [x] The oath facts are checked against the current patch and any difference is recorded in the spec's Further Notes before building on them.
- [x] The oath panel is enabled only at fixed difficulty 30, shows the points total and is remembered; covered by GUI tests.
- [x] Start and Resume carry oath ranks into `farmer.cfg`; malformed ranks are rejected; covered by tests.
- [x] A verify scenario at difficulty 30 shows the chosen oath points on the run in status and journal, and the profile's own oath set unchanged.
- [x] Invalid oath choices end the session as a failure naming the field.
- [x] Static checks and the pytest suite pass.

Spec: [`../spec.md`](../spec.md).
