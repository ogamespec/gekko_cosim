import sys, json, time
sys.path.insert(0, ".")
import netlist_slice as ns
from netlist_stream import Stream
s = Stream(); d, _ = ns.load_trace()
regs = json.load(open("research/gt_regs.json"))
sl = ns.Slicer(s, {}, regvals=regs["init"]); sl.run_pass(ns.order_for(d, "init"))
rows = [ns.stmt_parts(x) for x in sl.statements]
t0 = time.time()
mx = 0; mxst = None; hist = {}
for a,b,slot,v,bmask,wsrc in rows:
    if not bmask: continue
    g = ns.graph_nodes(v, 10**9)
    hist[min(g,10)] = hist.get(min(g,10),0)+1
    if g > mx: mx, mxst = g, (a, v)
print("identity-based graph_nodes: max %d @%08x in %.1fs" % (mx, mxst[0], time.time()-t0))
print("histogram (10=10+):", sorted(hist.items()))
# compare with a value-based traversal on the same node
def value_nodes(n, limit=10**9):
    seen = set(); cnt = 0; stack=[n]
    while stack:
        cur = stack.pop()
        if cur in seen: continue
        seen.add(cur)
        if ns.is_clause(cur):
            cnt += 1
            if cnt >= limit: return cnt
            for _s, a in ns.clause_lits(cur):
                if ns.is_clause(a): stack.append(a)
    return cnt
a, v = mxst
print("value-based on the same statement: %d" % value_nodes(v, 10**9))
