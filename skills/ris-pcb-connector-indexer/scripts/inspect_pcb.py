#!/usr/bin/env python3
"""Inspect Altium PcbDoc components/pad counts and via spans before tracing."""
from __future__ import annotations
import argparse, collections
from altium_pcb import PcbBoard

ap = argparse.ArgumentParser()
ap.add_argument("pcbdoc")
ap.add_argument("--min-named-pads", type=int, default=1)
args = ap.parse_args()
board = PcbBoard(args.pcbdoc)
counts = collections.Counter(p.comp for p in board.pads if p.designator.strip())
print(f"components={len(board.components)} pads={len(board.pads)} vias={len(board.vias)} tracks={len(board.tracks)}")
print("\nComponents with named pads:")
for c in sorted(board.components, key=lambda c: counts[c.index], reverse=True):
    n = counts[c.index]
    if n >= args.min_named_pads:
        print(f"  idx={c.index:<4} designator={c.designator or '(blank)':<12} named_pads={n}")
print("\nVia span histogram:")
for span, n in collections.Counter((v.start_layer, v.end_layer) for v in board.vias).most_common():
    print(f"  {span[0]}:{span[1]}  {n}")
