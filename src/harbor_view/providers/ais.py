"""The AIS provider, backed by AISStream.io.

Connects to AISStream.io's public WebSocket feed
(wss://stream.aisstream.io/v0/stream), listens for a short window,
merges position and static-data messages per vessel, and returns
whatever complete, drawable vessels it collected as plain `Vessel`
objects. See docs/sprint-004-notes.md for the full writeup, including
why a streaming API is wrapped in something `get_vessels()` (a
synchronous, single-shot call) can use.

Failure handling, per the Sprint 4 brief: ANY failure -- missing API
key, DNS/network failure, auth rejection, malformed messages, a listen
window that times out with nothing collected -- results in `[]`, never
an exception and never a silent fallback to placeholder data. An empty
harbor is treated as a valid, honest state: it means "nothing
confirmed in view," not "nothing is happening." Errors are logged via
the standard `logging` module rather than printed, so a deployment can
decide how/whether to surface them without Harbor View's own code
needing to change.
"""
from __future__ import annotations

import asyncio
import json
import logging
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
        """A vessel is drawable once it has a position, a heading, a
        name, and an AIS type code we know how to map to a
        `VesselType`. Anything less and Harbor View has nowhere to put
        it on the chart or no glyph to draw -- per the brief,
        incomplete records are dropped rather than guessed at.
        """
        if self.latitude is None or self.longitude is None:
            return False
        if self.heading_deg is None:
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
            heading_deg=self.heading_deg,
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
    -- see docs/sprint-004-notes.md):

      AISSTREAM_API_KEY          required; no default. If unset,
                                  get_vessels() logs a warning and
                                  returns [] immediately without
                                  attempting a connection.
      HARBOR_VIEW_AIS_BBOX       optional "lat1,lon1,lat2,lon2";
                                  defaults to a box around Port
                                  Everglades / Fort Lauderdale Beach.
      HARBOR_VIEW_AIS_LISTEN_SECONDS
                                  optional float; defaults to 12.

    Every failure mode -- no key, unreachable host, auth rejected,
    malformed JSON, nothing collected before the listen window ends --
    results in an empty list, logged at WARNING or ERROR, never an
    exception raised to the caller.
    """

    def __init__(
        self,
        api_key: str | None = None,
        bounding_box: tuple[tuple[float, float], tuple[float, float]] | None = None,
        listen_seconds: float | None = None,
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

    def get_vessels(self) -> list[Vessel]:
        if not self._api_key:
            logger.warning(
                "AISSTREAM_API_KEY is not set; returning an empty vessel "
                "list. Set the environment variable to enable live AIS -- "
                "see docs/sprint-004-notes.md."
            )
            return []

        try:
            partials = asyncio.run(self._collect())
        except Exception:
            # Deliberately broad: ANY failure here (DNS, TCP, TLS,
            # websocket handshake/auth rejection, asyncio plumbing,
            # an unexpected exception from a malformed message we
            # didn't anticipate) must degrade to an empty harbor, not
            # propagate to the renderer. The specific exception is
            # still logged with a full traceback for diagnosis.
            logger.exception(
                "AISProvider failed to retrieve live vessel data; "
                "returning an empty vessel list."
            )
            return []

        vessels = [p.to_vessel() for p in partials.values() if p.is_drawable()]
        logger.info(
            "AISProvider collected %d raw vessel record(s), %d drawable.",
            len(partials), len(vessels),
        )
        return vessels

    async def _collect(self) -> dict[str, _PartialVessel]:
        """Open the websocket, subscribe, and accumulate messages for
        `self._listen_seconds`. Returns whatever partial vessel state
        was built up, drawable or not -- filtering to drawable-only
        happens in get_vessels() so this method stays a pure "what did
        the feed say" collector.
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

        partials: dict[str, _PartialVessel] = {}

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
                self._handle_message(raw, partials)

        return partials

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
