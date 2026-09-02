#!/usr/bin/env python3
"""Small helper to inspect an extracted mapping without opening Excel."""
from __future__ import annotations
import argparse, json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("mapping_json")
ap.add_argument("--head", type=int, default=12)
ap.add_argument("--tail", type=int, default=6)
args = ap.parse_args()
rows = json.loads(Path(args.mapping_json).read_text(encoding="utf-8"))
print(f"rows={len(rows)} unique_pins={len({r['pin'] for r in rows})}")
for r in rows[: args.head]:
    print(f"{r['signal']:>4}  R{r['array_row']:02d}C{r['array_col']:02d}  {r['pin']:<8}  ({r['x_mm']:.3f}, {r['y_mm']:.3f})")
if len(rows) > args.head + args.tail:
    print("...")
for r in rows[-args.tail :]:
    print(f"{r['signal']:>4}  R{r['array_row']:02d}C{r['array_col']:02d}  {r['pin']:<8}  ({r['x_mm']:.3f}, {r['y_mm']:.3f})")
