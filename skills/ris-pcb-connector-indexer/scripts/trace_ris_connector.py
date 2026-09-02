#!/usr/bin/env python3
"""Trace RIS control vias to a connector in an Altium PcbDoc."""
from __future__ import annotations

import argparse, collections, csv, json, math, re
from pathlib import Path

try:
    from shapely.geometry import LineString, Point, box
    from shapely.strtree import STRtree
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'shapely'. Install with: pip install -r requirements.txt\n"
        f"Original import error: {exc}"
    )

from altium_pcb import MULTILAYER_ID, PcbBoard, PcbParseError


class MappingError(RuntimeError):
    pass


class DSU:
    def __init__(self, n):
        self.p = list(range(n)); self.r = [0] * n
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b: return
        if self.r[a] < self.r[b]: a, b = b, a
        self.p[b] = a
        if self.r[a] == self.r[b]: self.r[a] += 1


def _parse_span(s):
    if not s or s.lower() == "auto": return None
    m = re.fullmatch(r"\s*(\d+)\s*[:,-]\s*(\d+)\s*", s)
    if not m: raise argparse.ArgumentTypeError("source span must be 'auto' or like 1:32")
    return int(m.group(1)), int(m.group(2))


def _parse_bbox(s):
    if not s: return None
    v = [float(x.strip()) for x in s.split(",")]
    if len(v) != 4 or v[0] > v[2] or v[1] > v[3]:
        raise argparse.ArgumentTypeError("bbox must be min_x,min_y,max_x,max_y in mm")
    return tuple(v)


def _parse_anchor(s):
    m = re.fullmatch(r"\s*(\d+)\s*=\s*(\S+)\s*", s)
    if not m: raise argparse.ArgumentTypeError("anchor must look like 1=A21")
    return int(m.group(1)), m.group(2)


def resolve_connector(board, connector, expected_count=None):
    if connector and connector.lower() != "auto": return board.component(connector)
    counts = collections.Counter(p.comp for p in board.pads if p.designator.strip())
    ranked = sorted(((c, counts[c.index]) for c in board.components if counts[c.index]), key=lambda x: x[1], reverse=True)
    if not ranked: raise MappingError("No component with named pads found")
    plausible = [(c, n) for c, n in ranked if n >= max(32, (expected_count or 0) // 4)]
    if len(plausible) == 1: return plausible[0][0]
    if len(ranked) == 1: return ranked[0][0]
    preview = ", ".join(f"{c.designator or '#'+str(c.index)}({n} pads)" for c, n in ranked[:8])
    raise MappingError("Connector is ambiguous; specify --connector. Candidates: " + preview)


def build_connectivity(board, connector, eps_mm=0.002, expected_count=None):
    comp = resolve_connector(board, connector, expected_count)
    pad_ids = [i for i, p in enumerate(board.pads) if p.comp == comp.index and p.designator.strip()]
    if not pad_ids: raise MappingError(f"No named pads found for connector {comp.designator}")
    tracks = [(i, t) for i, t in enumerate(board.tracks) if board.is_copper_layer(t.layer)]
    layers = sorted({t.layer for _, t in tracks})

    track_node, via_node, pad_node, nodes = {}, {}, {}, []
    for i, _ in tracks: track_node[i] = len(nodes); nodes.append(("t", i))
    for i, _ in enumerate(board.vias): via_node[i] = len(nodes); nodes.append(("v", i))
    for i in pad_ids: pad_node[i] = len(nodes); nodes.append(("p", i))
    dsu = DSU(len(nodes))

    by_layer = collections.defaultdict(list)
    for i, t in tracks: by_layer[t.layer].append((i, LineString([(t.x1,t.y1),(t.x2,t.y2)])))
    trees = {layer: STRtree([g for _, g in arr]) for layer, arr in by_layer.items()}

    for layer, arr in by_layer.items():
        tree = trees[layer]
        for ti, _ in arr:
            t = board.tracks[ti]
            for xy in ((t.x1,t.y1),(t.x2,t.y2)):
                p = Point(*xy)
                for j in tree.query(p.buffer(eps_mm)):
                    oi, geom = arr[int(j)]
                    if oi != ti and p.distance(geom) <= eps_mm: dsu.union(track_node[ti], track_node[oi])

    for vi, v in enumerate(board.vias):
        lo, hi = sorted((v.start_layer, v.end_layer))
        if hi < 1 or lo > 32: continue
        radius = max(v.diameter/2, 0.0) + eps_mm
        q = Point(v.x, v.y).buffer(radius)
        for layer in layers:
            if not lo <= layer <= hi: continue
            arr = by_layer[layer]
            for j in trees[layer].query(q):
                ti, _ = arr[int(j)]; t = board.tracks[ti]
                if min(math.hypot(t.x1-v.x,t.y1-v.y), math.hypot(t.x2-v.x,t.y2-v.y)) <= radius:
                    dsu.union(via_node[vi], track_node[ti])

    for pi, node in pad_node.items():
        p = board.pads[pi]
        pl = layers if p.layer == MULTILAYER_ID else ([p.layer] if board.is_copper_layer(p.layer) else [])
        hx, hy = abs(p.sx)/2 + eps_mm, abs(p.sy)/2 + eps_mm
        q = box(p.x-hx,p.y-hy,p.x+hx,p.y+hy)
        for layer in pl:
            arr = by_layer.get(layer, [])
            if not arr: continue
            for j in trees[layer].query(q):
                ti, _ = arr[int(j)]; t = board.tracks[ti]
                hit = ((abs(t.x1-p.x)<=hx and abs(t.y1-p.y)<=hy) or
                       (abs(t.x2-p.x)<=hx and abs(t.y2-p.y)<=hy))
                if hit: dsu.union(node, track_node[ti])

    pins = collections.defaultdict(list)
    for pi, node in pad_node.items(): pins[dsu.find(node)].append(board.pads[pi].designator.strip())
    return dict(component=comp, connector_pad_indices=pad_ids, dsu=dsu, via_node=via_node, pins_by_root=pins)


def connected_unique_pin_vias(board, graph):
    out, ambiguous = [], []
    for vi, node in graph["via_node"].items():
        pins = sorted(set(graph["pins_by_root"].get(graph["dsu"].find(node), [])))
        if len(pins) == 1: out.append((vi, board.vias[vi], pins[0]))
        elif len(pins) > 1: ambiguous.append((vi, board.vias[vi], pins))
    return out, ambiguous


def choose_source_span(candidates, explicit_span, expected_count=None):
    groups = collections.defaultdict(list)
    for x in candidates: groups[(x[1].start_layer, x[1].end_layer)].append(x)
    if explicit_span is not None:
        if explicit_span not in groups:
            raise MappingError(f"Requested source span {explicit_span} not present; available: " + str({f'{a}:{b}':len(v) for (a,b),v in groups.items()}))
        return explicit_span, groups[explicit_span], groups
    if expected_count:
        exact = [(s,v) for s,v in groups.items() if len(v) == expected_count]
        if len(exact) == 1: return exact[0][0], exact[0][1], groups
        for s,v in exact:
            if s == (1,32): return s,v,groups
        if len(exact) > 1: raise MappingError("Multiple via spans match expected count; specify --source-span")
    if (1,32) in groups: return (1,32), groups[(1,32)], groups
    if not groups: raise MappingError("No vias traced to exactly one connector pin")
    s,v = max(groups.items(), key=lambda kv: len(kv[1])); return s,v,groups


def cluster_rows(items, tolerance_mm):
    rows, means = [], []
    for item in sorted(items, key=lambda x: -x[1].y):
        y = item[1].y
        if not rows or abs(y-means[-1]) > tolerance_mm: rows.append([item]); means.append(y)
        else:
            rows[-1].append(item); means[-1] = sum(x[1].y for x in rows[-1]) / len(rows[-1])
    return rows


def select_and_order_grid(items, expected_count, rows_expected, cols_expected, row_tolerance_mm, bbox_value):
    selected = list(items)
    if bbox_value:
        a,b,c,d = bbox_value; selected = [x for x in selected if a<=x[1].x<=c and b<=x[1].y<=d]
    clustered = cluster_rows(selected, row_tolerance_mm)
    if expected_count and len(selected) != expected_count and rows_expected and cols_expected:
        exact_rows = [r for r in clustered if len(r) == cols_expected]
        if len(exact_rows) == rows_expected: selected = [x for r in exact_rows for x in r]
    clustered = cluster_rows(selected, row_tolerance_mm)
    if expected_count is not None and len(selected) != expected_count:
        raise MappingError(f"Selected source-via count {len(selected)} != expected {expected_count}; row sizes: {[len(r) for r in clustered]}")
    if rows_expected is not None and len(clustered) != rows_expected:
        raise MappingError(f"Detected {len(clustered)} rows, expected {rows_expected}; row sizes: {[len(r) for r in clustered]}")
    if cols_expected is not None:
        bad = [(i+1,len(r)) for i,r in enumerate(clustered) if len(r) != cols_expected]
        if bad: raise MappingError(f"Rows do not contain expected {cols_expected} columns: {bad}")
    ordered = []
    for ri,row in enumerate(clustered,1):
        for ci,item in enumerate(sorted(row,key=lambda x:x[1].x),1): ordered.append((ri,ci,item))
    return ordered, clustered


def split_pin(pin):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", pin)
    if m: return m.group(1), int(m.group(2))
    if pin.isdigit(): return "", int(pin)
    return "", None


def write_outputs(out_dir, prefix, metadata, rows, connector_pads):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir/f"{prefix}_mapping.json", out_dir/f"{prefix}_mapping.csv", out_dir/f"{prefix}_connector_pins.csv", out_dir/f"{prefix}_diagnostics.json"]
    paths[0].write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    with paths[1].open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
    with paths[2].open("w",encoding="utf-8-sig",newline="") as f:
        fields=["connector","pin","layer","x_mm","y_mm","mapped_signal"]; w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(connector_pads)
    paths[3].write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    return paths


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcbdoc"); ap.add_argument("--connector",default="auto")
    ap.add_argument("--expected-count",type=int); ap.add_argument("--rows",type=int); ap.add_argument("--cols",type=int)
    ap.add_argument("--source-span",type=_parse_span); ap.add_argument("--row-tolerance-mm",type=float,default=0.25)
    ap.add_argument("--connect-tolerance-mm",type=float,default=0.002); ap.add_argument("--bbox",type=_parse_bbox)
    ap.add_argument("--anchor",action="append",type=_parse_anchor,default=[]); ap.add_argument("--out-dir",default="outputs")
    ap.add_argument("--prefix",default="ris_connector"); args=ap.parse_args(argv)
    if args.rows and args.cols and args.expected_count and args.rows*args.cols != args.expected_count:
        raise SystemExit("rows * cols must equal expected-count")
    try:
        board=PcbBoard(args.pcbdoc); graph=build_connectivity(board,args.connector,args.connect_tolerance_mm,args.expected_count)
        connector=graph["component"].designator or args.connector; candidates,ambiguous=connected_unique_pin_vias(board,graph)
        span,items,groups=choose_source_span(candidates,args.source_span,args.expected_count)
        ordered,row_clusters=select_and_order_grid(items,args.expected_count,args.rows,args.cols,args.row_tolerance_mm,args.bbox)
    except (PcbParseError,MappingError) as exc: raise SystemExit(f"ERROR: {exc}")

    rows=[]
    for signal,(ri,ci,(vi,v,pin)) in enumerate(ordered,1):
        pp,pn=split_pin(pin); rows.append(dict(signal=signal,array_row=ri,array_col=ci,x_mm=round(v.x,6),y_mm=round(v.y,6),connector=connector,pin=pin,pin_prefix=pp,pin_no=pn if pn is not None else "",via_index=vi,via_start_layer=v.start_layer,via_end_layer=v.end_layer,status="matched"))
    pins=[r["pin"] for r in rows]
    if len(set(pins)) != len(pins): raise SystemExit("ERROR: connector pins are not unique")
    anchors=dict(args.anchor)
    for signal,expected in anchors.items():
        if signal<1 or signal>len(rows): raise SystemExit(f"ERROR: anchor signal {signal} outside mapped range")
        if rows[signal-1]["pin"] != expected: raise SystemExit(f"ERROR: anchor failed: {signal} -> {rows[signal-1]['pin']}, expected {expected}")

    signal_by_pin={r["pin"]:r["signal"] for r in rows}; connector_pads=[]
    for pi in graph["connector_pad_indices"]:
        p=board.pads[pi]; connector_pads.append(dict(connector=connector,pin=p.designator.strip(),layer=p.layer,x_mm=round(p.x,6),y_mm=round(p.y,6),mapped_signal=signal_by_pin.get(p.designator.strip(),"")))
    meta=dict(source_file=Path(args.pcbdoc).name,connector=connector,connector_component_index=graph["component"].index,connector_named_pad_count=len(graph["connector_pad_indices"]),tracks=len(board.tracks),vias=len(board.vias),pads=len(board.pads),components=len(board.components),unique_pin_connected_vias=len(candidates),ambiguous_connector_connected_vias=len(ambiguous),source_span=list(span),via_span_histogram={f"{a}:{b}":len(v) for (a,b),v in sorted(groups.items())},selected_count=len(rows),detected_rows=len(row_clusters),row_sizes=[len(r) for r in row_clusters],unique_mapped_pins=len(set(pins)),order="top-view; left-to-right within row; top-to-bottom between rows",anchors_checked={str(k):v for k,v in anchors.items()},connect_tolerance_mm=args.connect_tolerance_mm,row_tolerance_mm=args.row_tolerance_mm,bbox=args.bbox,result="PASS")
    paths=write_outputs(args.out_dir,args.prefix,meta,rows,connector_pads)
    print(f"PASS: mapped {len(rows)} RIS controls to {len(set(pins))} unique {connector} pins")
    print(f"Source via span: {span[0]}:{span[1]}"); print(f"Detected grid: {len(row_clusters)} rows; row sizes = {[len(r) for r in row_clusters]}")
    if anchors: print(f"Anchors passed: {anchors}")
    for p in paths: print(p)


if __name__ == "__main__": main()
