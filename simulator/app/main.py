from __future__ import annotations
import os, re, subprocess, tempfile
from typing import Any
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Live Graph Simulator")

FORMULA_RE = re.compile(r"^[0-9aAbB+*/().\[\]\s-]+$")
NODE_TYPES = {"number", "add", "multiply", "divide", "display", "formula"}

class Graph(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def node_id(n): return str(n.get("id"))

def node_type(n): return n.get("data", {}).get("type") if n.get("type") == "custom" else (n.get("type") or n.get("data", {}).get("type"))

def data(n): return n.get("data", {})


def validate_formula(expr: str) -> str:
    expr = str(expr or "")
    if not expr or len(expr) > 200 or not FORMULA_RE.fullmatch(expr):
        raise ValueError("Formula may contain only numbers, a, b, +, -, *, / and brackets")
    if any(c in expr for c in "{};\n\r") or re.search(r"(?i)\\.?(control|end|shell|include|write|alter|let)\\b", expr):
        raise ValueError("Unsafe Formula rejected")
    if any(x not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+*/().[] -\t" for x in expr):
        raise ValueError("Formula contains a forbidden character")
    if re.search(r"(?i)\b(?:shell|control|end|include|write|alter)\b", expr):
        raise ValueError("Unsafe Formula rejected")
    depth = 0
    for c in expr:
        if c in "([": depth += 1
        elif c in ")]":
            depth -= 1
            if depth < 0: raise ValueError("Unbalanced brackets")
    if depth: raise ValueError("Unbalanced brackets")
    return expr.replace("[", "(").replace("]", ")")


def build_graph_info(g: Graph):
    nodes = {node_id(n): n for n in g.nodes}
    if len(nodes) != len(g.nodes): raise ValueError("Duplicate node id")
    for n in g.nodes:
        if node_type(n) not in NODE_TYPES: raise ValueError(f"Unknown node type on {node_id(n)}")
    incoming = {}
    outgoing = {nid: [] for nid in nodes}
    for e in g.edges:
        s, t = str(e.get("source")), str(e.get("target"))
        sh, th = str(e.get("sourceHandle") or "out"), str(e.get("targetHandle") or "in")
        if s not in nodes or t not in nodes: raise ValueError("Wire references missing node")
        if s == t: raise ValueError(f"Node {s} cannot connect to itself")
        if s not in outgoing: outgoing[s] = []
        key = (t, th)
        if key in incoming: raise ValueError(f"Input {th} on node {t} accepts only one wire")
        incoming[key] = (s, sh)
        outgoing[s].append(t)
    required = {"add": ["a","b"], "multiply": ["a","b"], "divide": ["a","b"], "display": ["x"], "formula": ["a","b"]}
    errors = []
    for nid,n in nodes.items():
        for h in required.get(node_type(n), []):
            if (nid,h) not in incoming:
                errors.append({"nodeId": nid, "message": f"Input {h} has no wire"})
        if node_type(n) == "formula":
            try: validate_formula(data(n).get("expression", ""))
            except ValueError as ex: errors.append({"nodeId": nid, "message": str(ex)})
    # cycle detection is intentionally run even when another validation error exists,
    # so the UI can highlight every relevant node in one response.
    state = {nid:0 for nid in nodes}; stack=[]; cycle_nodes=set()
    def dfs(u):
        state[u]=1; stack.append(u)
        for v in outgoing.get(u, []):
            if state[v]==0: dfs(v)
            elif state[v]==1:
                if v in stack:
                    cycle_nodes.update(stack[stack.index(v):])
        stack.pop(); state[u]=2
    for nid in nodes:
        if state[nid]==0: dfs(nid)
    if cycle_nodes:
        errors.extend({"nodeId": n, "message":"Node is part of a cycle"} for n in sorted(cycle_nodes))
    if errors:
        raise GraphError("Invalid graph", errors)
    return nodes, incoming, outgoing

class GraphError(Exception):
    def __init__(self, message, errors): self.message, self.errors = message, errors


def dsu_netlist(g: Graph, nodes, incoming):
    handles=[]
    for nid,n in nodes.items():
        t=node_type(n)
        if t != "display": handles.append(f"{nid}:out")
        for h in {"add":["a","b"],"multiply":["a","b"],"divide":["a","b"],"display":["x"],"formula":["a","b"]}.get(t,[]): handles.append(f"{nid}:{h}")
    parent={h:h for h in handles}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b):
        if a not in parent or b not in parent: return
        ra,rb=find(a),find(b)
        if ra!=rb: parent[rb]=ra
    for (tid,th),(sid,sh) in incoming.items(): union(f"{sid}:{sh}", f"{tid}:{th}")
    names={}; counter=1
    for h in handles:
        r=find(h)
        if r not in names: names[r]=f"N{counter}"; counter+=1
    def net(nid,h): return names[find(f"{nid}:{h}")]
    lines=[]; tracked=[]
    for nid,n in nodes.items():
        t=node_type(n); d=data(n)
        if t=="number":
            try: value=float(d.get("value",0))
            except: raise GraphError("Invalid Number", [{"nodeId":nid,"message":"Number must be numeric"}])
            lines.append(f"V_{safe(nid)} {net(nid,'out')} 0 DC {value}")
            tracked.append(net(nid,'out'))
        elif t in {"add","multiply","divide","formula"}:
            out=net(nid,'out'); a=net(nid,'a'); b=net(nid,'b'); name=f"B_{safe(nid)}"
            if t=="add": expr=f"V({a}) + V({b})"
            elif t=="multiply": expr=f"V({a}) * V({b})"
            elif t=="divide": expr=f"V({a}) / V({b})"
            else:
                raw=validate_formula(d.get("expression",""))
                expr=re.sub(r"\ba\b", f"V({a})", raw, flags=re.I)
                expr=re.sub(r"\bb\b", f"V({b})", expr, flags=re.I)
            lines.append(f"{name} {out} 0 V = {expr}")
            tracked.append(out)
        elif t=="display": tracked.append(net(nid,'x'))
    return lines, {nid:{h:net(nid,h) for h in ["out","a","b","x"] if f"{nid}:{h}" in parent} for nid in nodes}, list(dict.fromkeys(tracked))

def safe(s): return re.sub(r"[^A-Za-z0-9_]", "_", s)


def parse_values(text: str):
    vals={}
    # ngspice op output generally has "Index ... voltage" table. Accept several formats.
    for m in re.finditer(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s+([-+0-9.eE]+)\s*$", text):
        try: vals[m.group(1).lower()] = float(m.group(2))
        except ValueError: pass
    # Also parse v(name) = value style if emitted by a version/configuration.
    for m in re.finditer(r"(?i)\bV\(([^)]+)\)\s*[=:]\s*([-+0-9.eE]+)", text):
        try: vals[m.group(1).lower()] = float(m.group(2))
        except ValueError: pass
    return vals

@app.get("/health")
def health(): return {"ok": True}

@app.post("/simulate")
def simulate(graph: Graph):
    try:
        nodes, incoming, outgoing = build_graph_info(graph)
        lines, node_nets, tracked = dsu_netlist(graph, nodes, incoming)
        netlist="* generated by live-node-graph\n"+"\n".join(lines)+"\n.op\n.end\n"
    except GraphError as ex:
        return {"status":"error","errors":ex.errors,"message":ex.message,"nodeValues":{}}
    except ValueError as ex:
        return {"status":"error","errors":[{"nodeId":None,"message":str(ex)}],"message":str(ex),"nodeValues":{}}

    # Catch obvious zero denominators before ngspice, including zero produced by upstream constants/ops.
    # This is only an error preflight; valid computation still goes through ngspice.
    try:
        vals={}
        order=[]; indeg={n:0 for n in nodes}
        for s,vs in outgoing.items():
            for v in vs: indeg[v]+=1
        q=[n for n,d in indeg.items() if d==0]
        while q:
            u=q.pop(0); order.append(u)
            for v in outgoing.get(u,[]):
                indeg[v]-=1
                if indeg[v]==0:q.append(v)
        for nid in order:
            t=node_type(nodes[nid]); d=data(nodes[nid])
            if t=="number": vals[nid]=float(d.get("value",0))
            elif t in {"add","multiply","divide","formula"}:
                a_src=incoming[(nid,"a")][0]; b_src=incoming[(nid,"b")][0]
                a,b=vals[a_src],vals[b_src]
                if t=="add": vals[nid]=a+b
                elif t=="multiply": vals[nid]=a*b
                elif t=="divide":
                    if b==0: return {"status":"error","message":"Division by zero","errors":[{"nodeId":nid,"message":"Division by zero"}],"nodeValues":{}}
                    vals[nid]=a/b
                else:
                    # Do not use eval here; formula runtime remains ngspice's job.
                    pass
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as td:
        net=os.path.join(td,"graph.cir"); out=os.path.join(td,"graph.out")
        open(net,"w").write(netlist)
        try:
            p=subprocess.run(["ngspice","-b","-o",out,net],capture_output=True,text=True,timeout=4)
        except subprocess.TimeoutExpired:
            return {"status":"service_error","message":"ngspice timed out; the next edit will retry","nodeValues":{},"errors":[]}
        except FileNotFoundError:
            return {"status":"service_error","message":"ngspice is not installed","nodeValues":{},"errors":[]}
        report=(open(out).read() if os.path.exists(out) else "") + "\n" + p.stderr
        if p.returncode != 0:
            bad=[]
            for nid,n in nodes.items():
                if f"B_{safe(nid)}" in report or (node_type(n)=="divide" and "divide" in report.lower()):
                    bad.append({"nodeId":nid,"message":"ngspice reported an error for this node"})
            if not bad: bad=[{"nodeId":None,"message":"ngspice failed"}]
            return {"status":"error","message":"ngspice failed","errors":bad,"nodeValues":{}}
        parsed=parse_values(report)
        node_values={}
        for nid,nets in node_nets.items():
            t=node_type(nodes[nid])
            target = nets.get("out") if t!="display" else nets.get("x")
            if target and target.lower() in parsed: node_values[nid]=parsed[target.lower()]
        return {"status":"ok","message":"","nodeValues":node_values,"errors":[]}
