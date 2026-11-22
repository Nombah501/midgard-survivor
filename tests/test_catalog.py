import json

import pytest

from fake_smoke_game import CATALOG
from midgard_farm.core import catalog
from midgard_farm.platform import current


SNAPSHOT = {"index": 0, "id": "hero", "class": "archer", "job": "Sniper", "level": 35,
            "xp_progress": 0.8, "saved_at": 1767225600.5, "locked": False, "farmer": True}
TOWER = {"open": True, "hel_unlocked": True, "hel_reason": "", "checkpoints": [1, 11], "snapshots": [SNAPSHOT]}


def test_tower_catalog_reads_snapshot_metadata_and_native_checkpoints(tmp_path):
    (tmp_path / catalog.FILENAME).write_text(json.dumps(CATALOG | {"tower": TOWER}), encoding="utf-8")
    tower = catalog.tower_catalog(catalog.read_catalog(current(), tmp_path))
    assert tower is not None and tower.open and tower.hel_unlocked and not tower.hel_reason
    assert tower.checkpoints == (1, 11)
    assert tower.best_snapshot == catalog.TowerSnapshot(0, "hero", "archer", "Sniper", 35, 0.8,
                                                         1767225600.5, False, True)
    assert not catalog.tower_blocker(tower, "normal", 11)
    assert not catalog.tower_blocker(tower, "hel", 1)


@pytest.mark.parametrize("tower_fields", [None, TOWER | {"checkpoints": [11, 1]}, TOWER | {"open": 1}])
def test_legacy_or_invalid_tower_data_does_not_invalidate_ordinary_catalog(tmp_path, tower_fields):
    payload = CATALOG if tower_fields is None else CATALOG | {"tower": tower_fields}
    (tmp_path / catalog.FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    latest = catalog.read_catalog(current(), tmp_path)
    assert latest == payload
    assert catalog.tower_catalog(latest) is None
    assert "unavailable" in catalog.tower_blocker(None, "normal")


def test_tower_refuses_closed_or_unsuitable_snapshot_catalogs():
    closed = catalog.tower_catalog({"tower": TOWER | {"open": False}})
    assert "not open" in catalog.tower_blocker(closed, "normal")
    no_eligible_snapshot = catalog.tower_catalog({"tower": TOWER | {"snapshots": [
        SNAPSHOT | {"locked": True}, SNAPSHOT | {"xp_progress": 2.0}, SNAPSHOT | {"level": True},
    ]}})
    assert "No unlocked Tower snapshot" in catalog.tower_blocker(no_eligible_snapshot, "normal")
    duplicate = catalog.tower_catalog({"tower": TOWER | {"snapshots": [SNAPSHOT, SNAPSHOT | {"index": 1}]}})
    assert "ambiguous identity" in catalog.tower_blocker(duplicate, "normal")
