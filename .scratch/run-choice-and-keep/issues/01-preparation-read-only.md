# 01: Character preparation is read-only

**What to build:** The farmer never changes the character's preparation (ADR 0008): loadout, active pet, card album, distributed stats, rebirth, skill pick order, potential of worn items. The code that did it and its config keys are removed, not disabled. Storage cleanup and keep room-making never remove a worn item. A preset that still contains a removed key is refused before launch, naming the key.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] The farmer has no maintenance step that writes the loadout, active pet, album, stats, rebirth or pick order; unspent stat points stay unspent.
- [x] The removed keys (`auto_loadout`, `auto_pet`, `auto_cards`, `auto_stats`, `auto_rebirth`, `auto_rebirth_lv`, `override_pick_order`, `pet_priority`) are gone from every preset, the farmer's config validation and the farmer README.
- [x] Preflight refuses a preset (and a `farmer.cfg`) containing any removed key as unfixable, and the reason names the key; covered by a service launch test.
- [x] Star Smith, storage cleanup and keep room-making skip every item worn by any character.
- [x] A verify scenario runs a real run with every remaining maintenance action on and unspent stat points present, and judges loadout, pet, album, stats, rebirth state, pick order and worn-item potentials identical before and after.
- [x] Static checks and the pytest suite pass.

Spec: [`../spec.md`](../spec.md).
