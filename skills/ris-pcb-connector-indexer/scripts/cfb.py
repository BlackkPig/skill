"""Minimal Compound File Binary (CFB/OLE) reader used for Altium PcbDoc files.

This module intentionally implements only the read path required by this skill.
It has no third-party dependencies.
"""
from __future__ import annotations

import struct
from pathlib import Path

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
NOSTREAM = 0xFFFFFFFF
CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


class CFBError(RuntimeError):
    pass


class CFB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if len(self.data) < 512 or self.data[:8] != CFB_MAGIC:
            raise CFBError(f"Not a CFB/OLE file: {self.path}")

        h = self.data[:512]
        self.sector_shift = struct.unpack_from("<H", h, 30)[0]
        self.sector_size = 1 << self.sector_shift
        self.mini_sector_shift = struct.unpack_from("<H", h, 32)[0]
        self.mini_sector_size = 1 << self.mini_sector_shift
        self.num_fat_sectors = struct.unpack_from("<I", h, 44)[0]
        self.first_dir_sector = struct.unpack_from("<I", h, 48)[0]
        self.mini_cutoff = struct.unpack_from("<I", h, 56)[0]
        self.first_minifat_sector = struct.unpack_from("<I", h, 60)[0]
        self.num_minifat_sectors = struct.unpack_from("<I", h, 64)[0]
        self.first_difat_sector = struct.unpack_from("<I", h, 68)[0]
        self.num_difat_sectors = struct.unpack_from("<I", h, 72)[0]

        difat = [
            x
            for x in struct.unpack_from("<109I", h, 76)
            if x not in (FREESECT, ENDOFCHAIN)
        ]
        sec = self.first_difat_sector
        for _ in range(self.num_difat_sectors):
            if sec in (FREESECT, ENDOFCHAIN):
                break
            b = self.sector(sec)
            vals = list(struct.unpack(f"<{self.sector_size // 4}I", b))
            difat.extend(x for x in vals[:-1] if x not in (FREESECT, ENDOFCHAIN))
            sec = vals[-1]

        self.fat_sector_ids = difat[: self.num_fat_sectors]
        fat: list[int] = []
        for sid in self.fat_sector_ids:
            fat.extend(struct.unpack(f"<{self.sector_size // 4}I", self.sector(sid)))
        self.fat = fat

        dbytes = self.read_chain(self.first_dir_sector)
        self.entries: list[dict] = []
        for i in range(0, len(dbytes), 128):
            e = dbytes[i : i + 128]
            if len(e) < 128:
                break
            nlen = struct.unpack_from("<H", e, 64)[0]
            name = e[: max(0, nlen - 2)].decode("utf-16le", "ignore") if nlen >= 2 else ""
            obj_type = e[66]
            left, right, child = struct.unpack_from("<III", e, 68)
            start = struct.unpack_from("<I", e, 116)[0]
            size = struct.unpack_from("<Q", e, 120)[0]
            self.entries.append(
                {
                    "id": i // 128,
                    "name": name,
                    "type": obj_type,
                    "left": left,
                    "right": right,
                    "child": child,
                    "start": start,
                    "size": size,
                }
            )
        if not self.entries:
            raise CFBError("CFB directory is empty")
        self.root = self.entries[0]

        self.minifat: list[int] = []
        if self.num_minifat_sectors and self.first_minifat_sector not in (ENDOFCHAIN, FREESECT):
            mb = self.read_chain(self.first_minifat_sector, max_sectors=self.num_minifat_sectors)
            usable = len(mb) // 4 * 4
            self.minifat = list(struct.unpack(f"<{usable // 4}I", mb[:usable]))
        self.mini_stream = self.read_chain(self.root["start"])[: self.root["size"]]

        self.paths: dict[str, int] = {}
        self._walk_storage(0, [])

    def sector(self, sid: int) -> bytes:
        off = (sid + 1) * self.sector_size
        end = off + self.sector_size
        if off < 0 or end > len(self.data):
            raise CFBError(f"Sector {sid} outside file")
        return self.data[off:end]

    def chain_ids(self, start: int, table: list[int] | None = None, max_sectors: int | None = None):
        table = self.fat if table is None else table
        out: list[int] = []
        sid = start
        seen: set[int] = set()
        while sid not in (ENDOFCHAIN, FREESECT) and sid < len(table) and sid not in seen:
            out.append(sid)
            seen.add(sid)
            if max_sectors and len(out) >= max_sectors:
                break
            sid = table[sid]
        return out

    def read_chain(self, start: int, max_sectors: int | None = None) -> bytes:
        return b"".join(self.sector(s) for s in self.chain_ids(start, self.fat, max_sectors))

    def read_stream(self, entry: dict) -> bytes:
        size = entry["size"]
        if size == 0:
            return b""
        if size < self.mini_cutoff and entry["type"] == 2 and self.minifat:
            chunks = []
            for sid in self.chain_ids(entry["start"], self.minifat):
                off = sid * self.mini_sector_size
                chunks.append(self.mini_stream[off : off + self.mini_sector_size])
            return b"".join(chunks)[:size]
        return self.read_chain(entry["start"])[:size]

    def _sibling_tree(self, node_id: int):
        if node_id in (NOSTREAM, FREESECT) or node_id >= len(self.entries):
            return []
        e = self.entries[node_id]
        return self._sibling_tree(e["left"]) + [node_id] + self._sibling_tree(e["right"])

    def _walk_storage(self, storage_id: int, prefix: list[str]):
        st = self.entries[storage_id]
        for cid in self._sibling_tree(st["child"]):
            e = self.entries[cid]
            p = prefix + [e["name"]]
            self.paths["/".join(p)] = cid
            if e["type"] == 1:
                self._walk_storage(cid, p)

    def has(self, path: str) -> bool:
        return path in self.paths

    def get(self, path: str) -> bytes:
        if path not in self.paths:
            raise CFBError(f"Required stream not found: {path}")
        return self.read_stream(self.entries[self.paths[path]])
