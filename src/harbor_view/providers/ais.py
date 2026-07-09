"""The AIS provider, backed by AISStream.io.

Connects to AISStream.io's public WebSocket feed
(wss://stream.aisstream.io/v0/stream), listens for a short window,
merges position and static-data messages per vessel into a persistent
in-memory cache, and returns the drawable vessels from that cache.
See docs/sprint-004-notes.md for the original design writeup and
docs/sprint-006-notes.md for the cache architecture added in Sprint 6.

Cache design (Sprint 6)
-----------------------
AIS splits position ("where is it, which way is it heading") from
static data ("what is it called, what kind of vessel is it") across
two message types that arrive at very different rates: PositionReport
every few seconds for a moving Class A vessel, ShipStaticData roughly
every six minutes.  With a 12-second listen window, only vessels whose
six-minute static cycle happened to land inside that one window were
ever drawable.

The fix: keep a `dict[str, _PartialVessel]` keyed by MMSI as instance
state.  Each get_vessels() call merges newly-received messages into
this cache rather than discarding all state when the listen window
closes.  A vessel's type code and name, once learned from a single
ShipStaticData message, stay in the cache for subsequent calls that
only deliver PositionReports.  Vessels not seen in any message for
longer than `_DEFAULT_STALE_SECONDS` (15 minutes) are evicted so that
a vessel that has left the area does not linger on the chart
indefinitely.

The refresh loop (harbor_view.appliance.refresh_loop) already
constructs the provider once and reuses it for the process lifetime,
so the cache naturally warms across repeated get_vessels() calls.

Failure handling
----------------
If the connection to AISStream.io fails, get_vessels() logs the
exception and returns whatever is already in the cache rather than
clearing it.  A fresh provider with an empty cache still returns []
on connection failure (same as Sprint 4).  This preserves the
"empty harbor is a valid state" principle while not discarding
hard-won cache state on transient network hiccups.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field

from harbor_view.providers.ais_types import vessel_type_for_ais_code
from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselStatus

logger = logging.getLogger("harbor_view.providers.ais")

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# Default bounding box: a generous box around Port Everglades / Fort
# Lauderdale Beach (the chart's reference point, see
# harbor_view.chart.geometry.REF_LAT/REF_LON), wide enough to cover the
# chart's full view window (~7+ nm north-south, several nm offshore)
# with margin. Overridable via HARBOR_VIEW_AIS_BBOX so a deployment
# elsewhere doesn't require a code change -- see docs/sprint-004-notes.md.
_DEFAULT_BBOX = ((25.85, -80.30), (26.45, -79.85))

# How long to listen per get_vessels() call. AIS is a continuous
# stream, not a request/response API, so a single call has to decide
# when "enough" data has arrived. Position reports for nearby Class A
# vessels typically repeat every few seconds to a couple of minutes
# depending on speed; this window is a pragmatic balance between
# "give the renderer something" and "don't block a render for minutes."
# Overridable via HARBOR_VIEW_AIS_LISTEN_SECONDS.
_DEFAULT_LISTEN_SECONDS = 12.0

# How long a vessel can be absent from the AIS feed before it is
# considered gone and removed from the cache.  15 minutes gives the
# vessel's six-minute ShipStaticData cycle two full transmissions
# worth of margin before eviction, and is short enough that a vessel
# that leaves the bounding box does not linger on the chart for a
# significant fraction of a tidal cycle.  Overridable via
# HARBOR_VIEW_AIS_STALE_SECONDS.
_DEFAULT_STALE_SECONDS = 900.0

# AISStream requires the subscription message within 3 seconds of the
# socket opening, and connecting/authenticating can itself take a
# moment -- this bounds the connection attempt separately from the
# listen window above so a slow/unreachable host fails fast rather
# than eating the whole listen budget.
_CONNECT_TIMEOUT_SECONDS = 8.0


def _bbox_from_env() -> tuple[tuple[float, float], tuple[float, float]]:
    """Read HARBOR_VIEW_AIS_BBOX as "lat1,lon1,lat2,lon2" if set, else
    the Port Everglades default above. Malformed values fall back to
    the default rather than raising -- a bad bounding box shouldn't be
    able to crash startup any more than a network failure should crash
    a render.
    """
    raw = os.environ.get("HARBOR_VIEW_AIS_BBOX")
    if not raw:
        return _DEFAULT_BBOX
    try:
        parts = [float(p.strip()) for p in raw.split(",")]
        if len(parts) != 4:
            raise ValueError("expected exactly 4 comma-separated numbers")
        lat1, lon1, lat2, lon2 = parts
        return (lat1, lon1), (lat2, lon2)
    except ValueError:
        logger.warning(
            "HARBOR_VIEW_AIS_BBOX=%r is malformed (want \"lat1,lon1,lat2,lon2\"); "
            "using the default Port Everglades bounding box instead.",
            raw,
        )
        return _DEFAULT_BBOX


@dataclass
class _PartialVessel:
    """Accumulates what's been seen for one MMSI across however many
    PositionReport / ShipStaticData messages arrive during the listen
    window. AIS splits "where is it and which way is it pointed" from
    "what is it called and what kind of vessel is it" across two
    different message types that arrive independently and at
    different intervals -- this is the merge state for one vessel
    while we wait to (maybe) have both halves.
    """

    mmsi: str
    latitude: float | None = None
    longitude: float | None = None
    heading_deg: float | None = None
    speed_kn: float | None = None
    nav_status_code: int | None = None
    name: str | None = None
    ais_type_code: int | None = None
    destination: str | None = None
    last_seen_unix: float = field(default_factory=time.time)

    def is_drawable(self) -> bool:
        """A vessel is drawable once it has a position, a name, and an
        AIS type code we know how to map to a `VesselType`. Anything
        less and Harbor View has nowhere to put it on the chart or no
        glyph to draw -- per the brief, incomplete records are dropped
        rather than guessed at.

        Heading is treated as an optional rendering attribute. When
        unavailable, Harbor View renders the vessel with a default
        orientation rather than suppressing it entirely, because many
        legitimate AIS targets (especially anchored commercial vessels)
        report heading as unavailable.
        """
        if self.latitude is None or self.longitude is None:
            return False
        if not self.name or not self.name.strip():
            return False
        return vessel_type_for_ais_code(self.ais_type_code) is not None

    def to_vessel(self) -> Vessel:
        vessel_type = vessel_type_for_ais_code(self.ais_type_code)
        assert vessel_type is not None  # guaranteed by is_drawable()
        status = _nav_status_to_vessel_status(self.nav_status_code)
        destination = (self.destination or "").strip()
        # AIS pads free-text fields with "@" characters to a fixed
        # width at the protocol level; AISStream's JSON decoding
        # sometimes leaves these in. Strip trailing padding so
        # "NASSAU@@@@@@@" doesn't render literally.
        destination = destination.rstrip("@").strip()
        return Vessel(
            name=self.name.strip(),
            vessel_type=vessel_type,
            latitude=self.latitude,
            longitude=self.longitude,
            heading_deg=self.heading_deg if self.heading_deg is not None else 0.0,
            origin="",  # AIS has no concept of origin -- see models.py
            destination=destination,
            mmsi=self.mmsi,
            speed_kn=self.speed_kn,
            status=status,
        )


def _nav_status_to_vessel_status(code: int | None) -> VesselStatus:
    """AIS navigational status is an 8-value enumeration (0-15, with
    gaps); Harbor View only distinguishes a handful of coarse states.
    Unmapped/unknown codes become VesselStatus.UNKNOWN rather than a
    guess.
    """
    if code == 0:
        return VesselStatus.UNDERWAY
    if code == 1:
        return VesselStatus.AT_ANCHOR
    if code == 5:
        return VesselStatus.MOORED
    return VesselStatus.UNKNOWN


def _in_bounding_box(lat: float, lon: float, bbox) -> bool:
    (lat1, lon1), (lat2, lon2) = bbox
    lat_min, lat_max = min(lat1, lat2), max(lat1, lat2)
    lon_min, lon_max = min(lon1, lon2), max(lon1, lon2)
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


class AISProvider(VesselProvider):
    """Live vessel data from AISStream.io.

    Configuration is read from environment variables (never hardcoded
    -- see docs/sprint-004-notes.md and docs/sprint-006-notes.md):

      AISSTREAM_API_KEY          required; no default. If unset,
                                  get_vessels() logs a warning and
                                  returns [] immediately without
                                  attempting a connection.
      HARBOR_VIEW_AIS_BBOX       optional "lat1,lon1,lat2,lon2";
                                  defaults to a box around Port
                                  Everglades / Fort Lauderdale Beach.
      HARBOR_VIEW_AIS_LISTEN_SECONDS
                                  optional float; defaults to 12.
      HARBOR_VIEW_AIS_STALE_SECONDS
                                  optional float; defaults to 900 (15
                                  minutes).  Vessels not seen in any
                                  AIS message for longer than this
                                  threshold are evicted from the cache.

    Connection failures (no key, unreachable host, auth rejected,
    malformed JSON) are logged but do not raise.  A provider with a
    non-empty cache returns cached vessels on failure; a fresh provider
    with an empty cache returns [].
    """

    def __init__(
        self,
        api_key: str | None = None,
        bounding_box: tuple[tuple[float, float], tuple[float, float]] | None = None,
        listen_seconds: float | None = None,
        stale_seconds: float | None = None,
    ) -> None:
        # Explicit constructor args are supported for tests and for
        # callers that already have configuration in hand; the normal
        # path (and the only one used by default construction) is
        # reading from the environment.
        self._api_key = api_key if api_key is not None else os.environ.get("AISSTREAM_API_KEY")
        self._bbox = bounding_box if bounding_box is not None else _bbox_from_env()
        if listen_seconds is not None:
            self._listen_seconds = listen_seconds
        else:
            raw = os.environ.get("HARBOR_VIEW_AIS_LISTEN_SECONDS")
            try:
                self._listen_seconds = float(raw) if raw else _DEFAULT_LISTEN_SECONDS
            except ValueError:
                logger.warning(
                    "HARBOR_VIEW_AIS_LISTEN_SECONDS=%r is not a number; using %.0fs.",
                    raw, _DEFAULT_LISTEN_SECONDS,
                )
                self._listen_seconds = _DEFAULT_LISTEN_SECONDS
        if stale_seconds is not None:
            self._stale_seconds = stale_seconds
        else:
            raw = os.environ.get("HARBOR_VIEW_AIS_STALE_SECONDS")
            try:
                self._stale_seconds = float(raw) if raw else _DEFAULT_STALE_SECONDS
            except ValueError:
                logger.warning(
                    "HARBOR_VIEW_AIS_STALE_SECONDS=%r is not a number; using %.0fs.",
                    raw, _DEFAULT_STALE_SECONDS,
                )
                self._stale_seconds = _DEFAULT_STALE_SECONDS
        # Persistent per-vessel state, keyed by MMSI.  Survives across
        # get_vessels() calls for the lifetime of this provider instance.
        self._cache: dict[str, _PartialVessel] = {}
        self._messages_this_cycle: int = 0

    def get_vessels(self) -> list[Vessel]:
        if not self._api_key:
            logger.warning(
                "AISSTREAM_API_KEY is not set; returning an empty vessel "
                "list. Set the environment variable to enable live AIS -- "
                "see docs/sprint-004-notes.md."
            )
            return []

        self._messages_this_cycle = 0

        # Snapshot which MMSIs already had position/static data so we can
        # report what each listen window actually added.
        pre_position = {m for m, p in self._cache.items() if p.latitude is not None}
        pre_static = {m for m, p in self._cache.items() if p.ais_type_code is not None}

        try:
            # _collect merges new messages directly into self._cache.
            asyncio.run(self._collect(self._cache))
        except Exception:
            # Deliberately broad: ANY failure here (DNS, TCP, TLS,
            # websocket handshake/auth rejection, asyncio plumbing,
            # an unexpected exception from a malformed message we
            # didn't anticipate) must not propagate to the renderer.
            # Unlike Sprint 4, we do NOT return [] immediately: the
            # cache may already have valid vessel data from a previous
            # successful call, and discarding that on a transient
            # network failure would make the chart go blank
            # unnecessarily.  We log the failure, then fall through to
            # the eviction and drawable-filter steps below.
            logger.exception(
                "AISProvider failed to retrieve live vessel data; "
                "returning vessels from cache."
            )

        # Evict vessels not seen within the staleness window.
        now = time.time()
        stale_mmsis = [
            mmsi for mmsi, p in self._cache.items()
            if now - p.last_seen_unix > self._stale_seconds
        ]
        for mmsi in stale_mmsis:
            del self._cache[mmsi]

        # Per-cycle cache breakdown: how the cache grew and what's drawable.
        has_position = {m for m, p in self._cache.items() if p.latitude is not None}
        has_static = {m for m, p in self._cache.items() if p.ais_type_code is not None}
        has_both = has_position & has_static
        new_positions = has_position - pre_position
        new_static = has_static - pre_static
        vessels = [p.to_vessel() for p in self._cache.values() if p.is_drawable()]
        logger.info(
            "AISProvider cache: total=%d  position=%d  static=%d  both=%d  "
            "drawable=%d  new_position=%d  new_static=%d  evicted=%d",
            len(self._cache),
            len(has_position),
            len(has_static),
            len(has_both),
            len(vessels),
            len(new_positions),
            len(new_static),
            len(stale_mmsis),
        )
        # Sprint 6.1 diagnostic: for every vessel with both position and
        # static data, log drawable status and the specific failure reason.
        # Investigation only -- does not change behavior or the returned list.
        if has_both:
            reject_counts: dict[str, int] = {
                "unmapped vessel type": 0,
                "missing name": 0,
                "other": 0,
            }
            for mmsi in sorted(has_both):
                p = self._cache[mmsi]
                mapped_type = vessel_type_for_ais_code(p.ais_type_code)
                drawable = p.is_drawable()
                reason: str | None = None
                if not drawable:
                    if not p.name or not p.name.strip():
                        reason = "missing name"
                    elif mapped_type is None:
                        reason = "unmapped vessel type"
                    else:
                        reason = "other"
                    reject_counts[reason] += 1
                hv_type_str = mapped_type.value.upper() if mapped_type is not None else "none"
                logger.info(
                    "  MMSI=%-12s  name=%-28s  lat=%8.4f  lon=%9.4f  "
                    "heading=%-8s  ais_type=%-4s  hv_type=%-8s  drawable=%s%s",
                    mmsi,
                    repr(p.name),
                    p.latitude,
                    p.longitude,
                    str(p.heading_deg) if p.heading_deg is not None else "none",
                    str(p.ais_type_code),
                    hv_type_str,
                    "yes" if drawable else "no",
                    f"  reason={reason}" if reason else "",
                )
            logger.info(
                "Rejection summary (both=true, drawable=false):\n"
                "  %-30s  %s\n"
                "  %s\n"
                "  %-30s  %d\n"
                "  %-30s  %d\n"
                "  %-30s  %d",
                "Reason", "Count",
                "-" * 40,
                "unmapped vessel type", reject_counts["unmapped vessel type"],
                "missing name", reject_counts["missing name"],
                "other", reject_counts["other"],
            )

        if os.environ.get("HARBOR_VIEW_DEBUG_AIS"):
            self._print_debug_table()

        return vessels

    def _print_debug_table(self) -> None:
        """Print a per-vessel AIS reconciliation table to stdout.

        Enabled by setting HARBOR_VIEW_DEBUG_AIS to any non-empty value.
        Intended for manual comparison against MarineTraffic or another live
        AIS source; has no effect on rendering.
        """
        # Procedural renderer viewport geometry — inlined here to avoid the
        # circular import that would occur if we imported from chart.render
        # (which imports from this module). Values must stay in sync with
        # render.py constants.
        _NM = 1852.0
        _VIEW_HALF_HEIGHT_NM = 7.2
        _COAST_FRAC_FROM_LEFT = 0.21
        _MARGIN_FRAC = 0.018
        _SIDEBAR_FRAC = 0.25
        _FIG_W_IN, _FIG_H_IN = 10.0, 14.0

        _map_left = _SIDEBAR_FRAC + _MARGIN_FRAC * 0.6
        _panel_w_in = (1.0 - _map_left - _MARGIN_FRAC) * _FIG_W_IN
        _panel_h_in = (1.0 - 2 * _MARGIN_FRAC) * _FIG_H_IN
        _y_span_m = _VIEW_HALF_HEIGHT_NM * 2 * _NM
        _x_span_m = _y_span_m / (_panel_h_in / _panel_w_in)
        _x_min = -_COAST_FRAC_FROM_LEFT * _x_span_m
        _x_max = _x_min + _x_span_m
        _y_min = -_VIEW_HALF_HEIGHT_NM * _NM
        _y_max = _VIEW_HALF_HEIGHT_NM * _NM

        # Equirectangular projection matching chart.geometry.
        _REF_LAT, _REF_LON = 26.0906, -80.1095
        _M_PER_DEG = 111320.0
        _COS_REF = math.cos(math.radians(_REF_LAT))

        def _to_xy(lat: float, lon: float) -> tuple[float, float]:
            return ((lon - _REF_LON) * _COS_REF * _M_PER_DEG,
                    (lat - _REF_LAT) * _M_PER_DEG)

        def _in_vp(lat: float, lon: float) -> bool:
            x, y = _to_xy(lat, lon)
            return _x_min <= x <= _x_max and _y_min <= y <= _y_max

        _NAV_LABELS: dict[int, str] = {
            0: "UNDERWAY", 1: "AT_ANCHOR", 2: "NOT_UNDER_COMMAND",
            3: "RESTR_MANOEUVRABILITY", 4: "DRAUGHT_CONSTRAINED",
            5: "MOORED", 6: "AGROUND", 7: "FISHING", 8: "SAILING",
            15: "UNDEFINED",
        }

        now = time.time()
        n_in_vp_any = n_rendered = n_filtered = n_outside_vp = 0

        header = (
            f"{'MMSI':<12}  {'Name':<28}  {'AIS':>3}  {'HV Type':<8}  "
            f"{'Lat':>8}  {'Lon':>9}  {'Hdg':>5}  {'Spd':>5}  "
            f"{'Nav Status':<22}  {'Age':>6}  {'Rndr':<4}  Reason"
        )
        sep = "-" * len(header)

        print()
        print("=" * len(header))
        print("HARBOR VIEW — AIS DEBUG RECONCILIATION TABLE")
        print("=" * len(header))
        print(header)
        print(sep)

        for mmsi in sorted(self._cache):
            p = self._cache[mmsi]
            age_s = now - p.last_seen_unix
            has_pos = p.latitude is not None and p.longitude is not None
            has_name = bool(p.name and p.name.strip())
            hv_type = vessel_type_for_ais_code(p.ais_type_code)

            in_vp = has_pos and _in_vp(p.latitude, p.longitude)
            if in_vp:
                n_in_vp_any += 1

            rendered = False
            reason = ""
            if not has_pos:
                reason = "missing position"
                n_filtered += 1
            elif not has_name:
                reason = "missing name"
                n_filtered += 1
            elif hv_type is None:
                reason = f"unsupported type ({p.ais_type_code})"
                n_filtered += 1
            elif not in_vp:
                reason = "outside viewport"
                n_outside_vp += 1
            else:
                rendered = True
                n_rendered += 1

            ais_str = str(p.ais_type_code) if p.ais_type_code is not None else "—"
            hv_str = hv_type.value.upper() if hv_type else "none"
            lat_str = f"{p.latitude:.4f}" if has_pos else "—"
            lon_str = f"{p.longitude:.4f}" if has_pos else "—"
            hdg_str = f"{p.heading_deg:.0f}" if p.heading_deg is not None else "—"
            spd_str = f"{p.speed_kn:.1f}" if p.speed_kn is not None else "—"
            if p.nav_status_code is not None:
                nav_str = _NAV_LABELS.get(p.nav_status_code, f"code={p.nav_status_code}")
            else:
                nav_str = "—"
            name_str = (p.name.strip() if p.name else "—")[:28]

            print(
                f"{mmsi:<12}  {name_str:<28}  {ais_str:>3}  {hv_str:<8}  "
                f"{lat_str:>8}  {lon_str:>9}  {hdg_str:>5}  {spd_str:>5}  "
                f"{nav_str:<22}  {age_s:>5.0f}s  {'YES' if rendered else 'NO':<4}  {reason}"
            )

        print(sep)
        print()
        print(f"  Total AIS messages received this cycle : {self._messages_this_cycle}")
        print(f"  Unique vessels in cache (post-eviction): {len(self._cache)}")
        print(f"  Vessels inside viewport                : {n_in_vp_any}")
        print(f"  Vessels rendered                       : {n_rendered}")
        print(f"  Vessels filtered (missing data/type)   : {n_filtered}")
        print(f"  Vessels outside viewport               : {n_outside_vp}")
        print()
        print("=" * len(header))
        print()

    async def _collect(self, cache: dict[str, _PartialVessel]) -> None:
        """Open the websocket, subscribe, and accumulate messages for
        `self._listen_seconds` into `cache`.

        Messages are merged directly into `cache` via `_handle_message`,
        so previously-learned fields (name, AIS type code) are preserved
        across calls.  Returns None -- the caller owns `cache`.
        """
        # Imported here rather than at module level: this keeps the
        # `websockets` dependency lazy, so importing
        # harbor_view.providers.ais (e.g. for type-checking or for
        # AISProvider's docstring) doesn't require the package to be
        # installed in environments that never actually construct an
        # AISProvider. See docs/sprint-004-notes.md for the dependency
        # justification.
        import websockets

        (lat1, lon1), (lat2, lon2) = self._bbox
        subscribe_message = {
            "APIKey": self._api_key,
            "BoundingBoxes": [[[lat1, lon1], [lat2, lon2]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

        async with await asyncio.wait_for(
            websockets.connect(AISSTREAM_URL), timeout=_CONNECT_TIMEOUT_SECONDS
        ) as ws:
            # AISStream requires the subscription within 3 seconds of
            # connecting; sending it immediately after connect leaves
            # ample margin.
            await ws.send(json.dumps(subscribe_message))

            deadline = time.monotonic() + self._listen_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                self._handle_message(raw, cache)

    def _handle_message(self, raw, partials: dict[str, _PartialVessel]) -> None:
        """Parse one websocket frame and fold it into `partials`.
        Any single malformed/unexpected message is logged and skipped
        -- it must never abort the whole listen session, per the
        brief's "gracefully ignore incomplete or malformed records."
        """
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Ignoring non-JSON AIS frame.")
            return

        self._messages_this_cycle += 1

        try:
            message_type = envelope["MessageType"]
            metadata = envelope["MetaData"]
            mmsi = str(metadata["MMSI"])
        except (KeyError, TypeError):
            logger.debug("Ignoring AIS frame missing MessageType/MetaData/MMSI.")
            return

        lat = metadata.get("latitude")
        lon = metadata.get("longitude")
        if lat is None or lon is None:
            return
        if not _in_bounding_box(lat, lon, self._bbox):
            # AISStream's bounding-box filter is applied server-side,
            # but a redundant client-side check costs nothing and
            # guards against any vessel that straddles the edge of a
            # box or a future change to how the box is sent.
            return

        partial = partials.setdefault(mmsi, _PartialVessel(mmsi=mmsi))
        partial.latitude = lat
        partial.longitude = lon
        partial.last_seen_unix = time.time()

        ship_name = metadata.get("ShipName")
        if ship_name and ship_name.strip():
            partial.name = ship_name

        payload = envelope.get("Message", {}).get(message_type)
        if not isinstance(payload, dict):
            return

        if message_type == "PositionReport":
            heading = payload.get("TrueHeading")
            # AIS reports 511 for "heading not available." Cog
            # (course over ground) is used as a fallback so a vessel
            # without a working heading sensor doesn't get dropped
            # outright if it's at least moving in a known direction.
            if heading is None or heading == 511:
                heading = payload.get("Cog")
            if heading is not None:
                partial.heading_deg = float(heading)

            sog = payload.get("Sog")
            if sog is not None and sog != 102.3:  # 102.3 = "not available"
                partial.speed_kn = float(sog)

            nav_status = payload.get("NavigationalStatus")
            if nav_status is not None:
                partial.nav_status_code = int(nav_status)

        elif message_type == "ShipStaticData":
            ais_type = payload.get("Type")
            if ais_type is not None:
                partial.ais_type_code = int(ais_type)

            destination = payload.get("Destination")
            if destination is not None:
                partial.destination = destination

            name = payload.get("Name")
            if name and name.strip():
                partial.name = name
