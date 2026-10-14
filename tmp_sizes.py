import sys, json
sys.path.insert(0, ".")
import netlist_slice as ns
from netlist_stream import Stream
s = Stream(); d, _ = ns.load_trace()
regs = json.load(open("research/gt_regs.json"))
for r in ("init", "cycle2"):
    sl = ns.Slicer(s, {}, regvals=regs["init" if r=="init" else "cycle0_stage3"])
    sl.run_pass(ns.order_for(d, r))
    rows = [ns.stmt_parts(x) for x in sl.statements]
    sizes = [ns.graph_nodes(v, 10**9) for a,b,slot,v,bmask,wsrc in rows if bmask]
    sizes.sort(reverse=True)
    n = len(sizes)
    print("%-7s %6d expr statements: max %d, p99 %d, p90 %d, mean %.1f, "
          ">1000: %d, >100: %d"
          % (r, n, sizes[0], sizes[int(n*0.01)], sizes[int(n*0.10)],
             sum(sizes)/n, sum(1 for x in sizes if x > 1000),
             sum(1 for x in sizes if x > 100)))
