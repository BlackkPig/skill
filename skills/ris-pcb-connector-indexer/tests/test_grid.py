import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from trace_ris_connector import cluster_rows, select_and_order_grid

class V:
    def __init__(self, x, y):
        self.x=x; self.y=y

def item(i,x,y,pin):
    return (i,V(x,y),pin)

def test_top_left_row_major():
    items=[item(0,20,10,"P2"), item(1,10,10,"P1"), item(2,20,0,"P4"), item(3,10,0,"P3")]
    ordered, rows = select_and_order_grid(items,4,2,2,0.1,None)
    assert [x[2][2] for x in ordered] == ["P1","P2","P3","P4"]
    assert [(x[0],x[1]) for x in ordered] == [(1,1),(1,2),(2,1),(2,2)]
