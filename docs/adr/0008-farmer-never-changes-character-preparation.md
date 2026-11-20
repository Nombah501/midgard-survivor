# The farmer never changes the character's preparation

Status: accepted

The operator prepares each character by hand (loadout, pet, card album, distributed stats, rebirth, skill pick order, potential of worn items) and the farmer's own optimisers kept undoing that work between runs. The farmer now treats the character's preparation as read-only: it never changes any part of it, there is no setting that lets it, and the code that did (`_auto_loadout`, `_auto_pet`, `_auto_album`, `_auto_stats`, `_do_rebirth`, Star Smith on worn items) is removed. Unspent stat points stay unspent until the operator spends them.

## Considered Options

- **Lock only filled loadout slots and let the farmer fill empty ones:** rejected. Any farmer write into the loadout breaks "what I prepared is what runs".
- **Keep the optimisers behind off-by-default switches:** rejected. A switch can be turned on by accident in a preset, and the optimisers are code to maintain for a behaviour the operator does not want.

## Consequences

- Maintenance keeps only resource actions the operator switches on: Kafra/Sage upgrades, fusion of spare card copies, Star Smith on unworn stored items, and storage pruning.
- A character without a prepared loadout runs with whatever it wears; the farmer does not compensate.
- The game itself makes a newly earned pet active when no pet is selected; that is native game behaviour, not a farmer write, and is left as is.
