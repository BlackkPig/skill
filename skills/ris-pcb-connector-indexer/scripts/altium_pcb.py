"""Read the subset of Altium PcbDoc primitives needed for geometric connectivity tracing.

Supported/validated stream family: Components6, Pads6, Vias6, Tracks6.
Coordinates are converted to millimetres.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from cfb import CFB, CFBError

# Altium internal coordinate unit observed in binary PcbDoc v6 streams.
MM_PER_RAW = 2.54e-6
COPPER_LAYER_MIN = 1
COPPER_LAYER_MAX = 32
MULTILAYER_ID = 74


class PcbParseError(RuntimeError):
    pass


def _coord(raw4: bytes) -> float:
    return struct.unpack("<i", raw4)[0] * MM_PER_RAW


def _read_block(data: bytes, pos: int):
    if pos + 4 > len(data):
        raise PcbParseError("Unexpected end of Pads6 record")
    n = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    if pos + n > len(data):
        raise PcbParseError("Invalid length-prefixed Pads6 block")
    return data[pos : pos + n], pos + n


def _pascal_string(block: bytes) -> str:
    if not block:
        return ""
    n = block[0]
    return block[1 : 1 + n].decode("cp1252", "replace")


def _property_records(data: bytes):
    """Parse repeated <uint32 length><ASCII/UTF-8-ish property string> records."""
    pos = 0
    idx = 0
    while pos + 4 <= len(data):
        n = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if n == 0:
            yield idx, ""
            idx += 1
            continue
        if pos + n > len(data):
            raise PcbParseError(f"Invalid text record length at record {idx}")
        raw = data[pos : pos + n]
        pos += n
        yield idx, raw.rstrip(b"\x00").decode("cp1252", "replace")
        idx += 1


def _parse_pipe_properties(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in text.split("|"):
        if "=" in token:
            key, value = token.split("=", 1)
            if key:
                out[key.upper()] = value
    return out


@dataclass
class Component:
    index: int
    designator: str
    properties: dict[str, str]


@dataclass
class Track:
    index: int
    layer: int
    net: int
    comp: int
    x1: float
    y1: float
    x2: float
    y2: float
    width: float


@dataclass
class Via:
    index: int
    layer: int
    net: int
    comp: int
    x: float
    y: float
    diameter: float
    hole: float
    start_layer: int
    end_layer: int


@dataclass
class Pad:
    index: int
    designator: str
    net_string: str
    layer: int
    net: int
    comp: int
    x: float
    y: float
    sx: float
    sy: float
    hole: float
    shape: int | None


class PcbBoard:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.cfb = CFB(self.path)
        required = ["Components6/Data", "Pads6/Data", "Vias6/Data", "Tracks6/Data"]
        missing = [p for p in required if not self.cfb.has(p)]
        if missing:
            raise PcbParseError(
                "Unsupported PcbDoc stream layout. Missing: " + ", ".join(missing)
            )
        self.components = self._parse_components()
        self.pads = self._parse_pads()
        self.vias = self._parse_vias()
        self.tracks = self._parse_tracks()

    def _parse_components(self):
        out: list[Component] = []
        for idx, text in _property_records(self.cfb.get("Components6/Data")):
            props = _parse_pipe_properties(text)
            designator = props.get("SOURCEDESIGNATOR", "").strip()
            out.append(Component(idx, designator, props))
        return out

    def _parse_tracks(self):
        data = self.cfb.get("Tracks6/Data")
        pos = 0
        out: list[Track] = []
        ridx = 0
        while pos + 5 <= len(data):
            typ = data[pos]
            pos += 1
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            rec = data[pos : pos + n]
            pos += n
            if typ != 4:
                raise PcbParseError(f"Unexpected Tracks6 record type {typ} at {ridx}")
            if len(rec) < 33:
                ridx += 1
                continue
            out.append(
                Track(
                    index=ridx,
                    layer=rec[0],
                    net=struct.unpack_from("<H", rec, 3)[0],
                    comp=struct.unpack_from("<H", rec, 7)[0],
                    x1=_coord(rec[13:17]),
                    y1=_coord(rec[17:21]),
                    x2=_coord(rec[21:25]),
                    y2=_coord(rec[25:29]),
                    width=_coord(rec[29:33]),
                )
            )
            ridx += 1
        return out

    def _parse_vias(self):
        data = self.cfb.get("Vias6/Data")
        pos = 0
        out: list[Via] = []
        ridx = 0
        while pos + 5 <= len(data):
            typ = data[pos]
            pos += 1
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            rec = data[pos : pos + n]
            pos += n
            if typ != 3:
                raise PcbParseError(f"Unexpected Vias6 record type {typ} at {ridx}")
            if len(rec) < 31:
                ridx += 1
                continue
            out.append(
                Via(
                    index=ridx,
                    layer=rec[0],
                    net=struct.unpack_from("<H", rec, 3)[0],
                    comp=struct.unpack_from("<H", rec, 7)[0],
                    x=_coord(rec[13:17]),
                    y=_coord(rec[17:21]),
                    diameter=_coord(rec[21:25]),
                    hole=_coord(rec[25:29]),
                    start_layer=rec[29],
                    end_layer=rec[30],
                )
            )
            ridx += 1
        return out

    def _parse_pads(self):
        data = self.cfb.get("Pads6/Data")
        pos = 0
        out: list[Pad] = []
        ridx = 0
        while pos < len(data):
            if pos + 1 > len(data):
                break
            typ = data[pos]
            pos += 1
            if typ != 2:
                raise PcbParseError(f"Unexpected Pads6 record type {typ} at {ridx}")
            blocks = []
            for _ in range(6):
                block, pos = _read_block(data, pos)
                blocks.append(block)
            des = _pascal_string(blocks[0])
            netstr = _pascal_string(blocks[2])
            main = blocks[4]
            if len(main) < 50:
                ridx += 1
                continue
            out.append(
                Pad(
                    index=ridx,
                    designator=des,
                    net_string=netstr,
                    layer=main[0],
                    net=struct.unpack_from("<H", main, 3)[0],
                    comp=struct.unpack_from("<H", main, 7)[0],
                    x=_coord(main[13:17]),
                    y=_coord(main[17:21]),
                    sx=_coord(main[21:25]),
                    sy=_coord(main[25:29]),
                    hole=_coord(main[45:49]),
                    shape=main[49],
                )
            )
            ridx += 1
        return out

    def component(self, designator: str) -> Component:
        wanted = designator.strip().upper()
        matches = [c for c in self.components if c.designator.upper() == wanted]
        if not matches:
            known = ", ".join(c.designator for c in self.components if c.designator) or "(none)"
            raise PcbParseError(f"Connector/component {designator!r} not found. Components: {known}")
        if len(matches) > 1:
            raise PcbParseError(f"Component designator {designator!r} is not unique")
        return matches[0]

    @staticmethod
    def is_copper_layer(layer: int) -> bool:
        return COPPER_LAYER_MIN <= layer <= COPPER_LAYER_MAX
