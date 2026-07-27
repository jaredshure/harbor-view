"""Unit tests for VesselCache.

VesselCache is the persistent in-memory store that accumulates
_PartialVessel entries across AIS listen windows.  These tests exercise
the cache in isolation -- no network, no provider, no monkeypatching.
"""
from __future__ import annotations

import time

import pytest

from harbor_view.providers.ais import VesselCache, _PartialVessel
from harbor_view.providers.models import VesselType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _partial(mmsi: str, **kwargs) -> _PartialVessel:
    """Return a _PartialVessel with the given MMSI and optional field overrides."""
    p = _PartialVessel(mmsi=mmsi)
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def _drawable(mmsi: str) -> _PartialVessel:
    """Return a _PartialVessel with a valid in-range position (drawable)."""
    return _partial(mmsi, latitude=26.1, longitude=-80.1)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_new_cache_is_empty():
    cache = VesselCache(cache_minutes=10)
    assert cache.size() == 0
    assert len(cache) == 0


def test_cache_ttl_stored_as_seconds():
    cache = VesselCache(cache_minutes=5)
    assert cache._ttl_seconds == 300.0


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------

def test_update_adds_new_mmsi():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    assert cache.size() == 1
    assert "111" in cache


def test_update_two_different_mmsis_are_separate_entries():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    cache.update(_drawable("222"))
    assert cache.size() == 2
    assert "111" in cache
    assert "222" in cache


def test_update_merges_non_none_fields():
    """PositionReport (lat/lon) then ShipStaticData (name/type): both must survive."""
    cache = VesselCache(cache_minutes=10)
    cache.update(_partial("111", latitude=26.1, longitude=-80.1))
    cache.update(_partial("111", name="CARGO SHIP", ais_type_code=70))
    p = cache["111"]
    assert p.latitude == 26.1       # from first update
    assert p.name == "CARGO SHIP"   # from second update
    assert p.ais_type_code == 70    # from second update


def test_update_preserves_existing_fields_when_incoming_has_none():
    """A PositionReport arriving after ShipStaticData must not clear the name."""
    cache = VesselCache(cache_minutes=10)
    cache.update(_partial("111", name="TUG BOAT", ais_type_code=52))
    cache.update(_partial("111", latitude=26.1, longitude=-80.1))
    p = cache["111"]
    assert p.name == "TUG BOAT"     # preserved: incoming.name was None
    assert p.ais_type_code == 52    # preserved: incoming.ais_type_code was None
    assert p.latitude == 26.1       # set by second update


def test_update_overwrites_existing_non_none_field():
    """A later update with a non-None value must replace the earlier one."""
    cache = VesselCache(cache_minutes=10)
    cache.update(_partial("111", name="OLD NAME"))
    cache.update(_partial("111", name="NEW NAME"))
    assert cache["111"].name == "NEW NAME"


def test_update_always_refreshes_last_seen_unix():
    cache = VesselCache(cache_minutes=10)
    early = time.time() - 100.0
    cache.update(_partial("111", last_seen_unix=early))
    assert cache["111"].last_seen_unix == pytest.approx(early, abs=1.0)

    later = time.time()
    cache.update(_partial("111", last_seen_unix=later))
    assert cache["111"].last_seen_unix == pytest.approx(later, abs=1.0)


# ---------------------------------------------------------------------------
# expire()
# ---------------------------------------------------------------------------

def test_expire_removes_stale_entry():
    cache = VesselCache(cache_minutes=1)
    cache.update(_partial("111", last_seen_unix=time.time() - 120.0))  # 2 min ago > 1 min TTL
    expired = cache.expire(time.time())
    assert expired == 1
    assert cache.size() == 0


def test_expire_preserves_fresh_entry():
    cache = VesselCache(cache_minutes=10)
    cache.update(_partial("111", last_seen_unix=time.time() - 30.0))  # 30 s ago < 10 min TTL
    expired = cache.expire(time.time())
    assert expired == 0
    assert cache.size() == 1


def test_expire_returns_count_of_evicted_entries():
    cache = VesselCache(cache_minutes=1)
    old = time.time() - 120.0
    cache.update(_partial("111", last_seen_unix=old))
    cache.update(_partial("222", last_seen_unix=old))
    cache.update(_partial("333", last_seen_unix=time.time()))  # fresh
    expired = cache.expire(time.time())
    assert expired == 2
    assert "333" in cache
    assert "111" not in cache
    assert "222" not in cache


def test_expire_on_empty_cache_returns_zero():
    cache = VesselCache(cache_minutes=10)
    assert cache.expire(time.time()) == 0


def test_expire_exactly_at_boundary_is_not_evicted():
    cache = VesselCache(cache_minutes=1)
    # Pin a single 'now' so age == TTL exactly (not strictly greater) → kept.
    now = time.time()
    cache.update(_partial("111", last_seen_unix=now - 60.0))
    assert cache.expire(now) == 0


# ---------------------------------------------------------------------------
# drawable_vessels()
# ---------------------------------------------------------------------------

def test_drawable_vessels_returns_only_entries_with_valid_position():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    cache.update(_partial("222"))  # no position — not drawable
    vessels = cache.drawable_vessels()
    assert len(vessels) == 1
    assert vessels[0].mmsi == "111"


def test_drawable_vessels_empty_cache_returns_empty_list():
    cache = VesselCache(cache_minutes=10)
    assert cache.drawable_vessels() == []


def test_drawable_vessels_returns_vessel_objects():
    from harbor_view.providers.models import Vessel
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    vessels = cache.drawable_vessels()
    assert all(isinstance(v, Vessel) for v in vessels)


# ---------------------------------------------------------------------------
# size() and clear()
# ---------------------------------------------------------------------------

def test_size_reflects_entry_count():
    cache = VesselCache(cache_minutes=10)
    assert cache.size() == 0
    cache.update(_drawable("111"))
    assert cache.size() == 1
    cache.update(_drawable("222"))
    assert cache.size() == 2


def test_clear_removes_all_entries():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    cache.update(_drawable("222"))
    cache.clear()
    assert cache.size() == 0
    assert "111" not in cache


# ---------------------------------------------------------------------------
# Dict-like interface (__contains__, __getitem__, __len__, __iter__, items())
# ---------------------------------------------------------------------------

def test_contains_true_for_existing_mmsi():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    assert "111" in cache


def test_contains_false_for_missing_mmsi():
    cache = VesselCache(cache_minutes=10)
    assert "999" not in cache


def test_getitem_returns_partial_vessel():
    cache = VesselCache(cache_minutes=10)
    p = _drawable("111")
    cache.update(p)
    result = cache["111"]
    assert isinstance(result, _PartialVessel)
    assert result.mmsi == "111"
    assert result.latitude == 26.1


def test_getitem_raises_for_missing_mmsi():
    cache = VesselCache(cache_minutes=10)
    with pytest.raises(KeyError):
        _ = cache["nonexistent"]


def test_getitem_returns_live_reference():
    """Mutating the returned object must be reflected in the cache."""
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    cache["111"].name = "MUTATED"
    assert cache["111"].name == "MUTATED"


def test_len_equals_size():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    cache.update(_drawable("222"))
    assert len(cache) == cache.size() == 2


def test_iter_yields_mmsi_strings():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    cache.update(_drawable("222"))
    mmsis = set(cache)
    assert mmsis == {"111", "222"}


def test_items_yields_mmsi_partial_pairs():
    cache = VesselCache(cache_minutes=10)
    cache.update(_drawable("111"))
    pairs = dict(cache.items())
    assert "111" in pairs
    assert isinstance(pairs["111"], _PartialVessel)
