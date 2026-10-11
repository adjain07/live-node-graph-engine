import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow,Background,Controls,MiniMap,Handle,Position,useEdgesState,useNodesState,addEdge,ReactFlowProvider,useReactFlow} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './styles.css';

const API='/api';
async function readApiJSON(response) {
 const contentType=response.headers.get('content-type')||'';
 if(!contentType.includes('application/json')){
  throw new Error(`API returned ${response.status} (${contentType||'unknown content type'}) instead of JSON. Check nginx /api proxy and Docker API service.`);
 }
 const body=await response.json();
 if(!response.ok && body.status!=='service_error')throw new Error(body.message||body.error||`API HTTP ${response.status}`);
 return body;
}
const defs={number:{label:'Number',inputs:[],output:true},add:{label:'Add',inputs:['a','b'],output:true},multiply:{label:'Multiply',inputs:['a','b'],output:true},divide:{label:'Divide',inputs:['a','b'],output:true},display:{label:'Display',inputs:['x'],output:false},formula:{label:'Formula',inputs:['a','b'],output:true}};
function NodeCard({id,data}){
 const def=defs[data.type]; const [local,setLocal]=useState(data.type==='formula'?(data.expression??''):(data.value??''));
 useEffect(()=>setLocal(data.type==='formula'?(data.expression??''):(data.value??'')),[data.type,data.value,data.expression]);
 const set=(patch)=>data.onChange(id,patch);
 return <div className={`node-card ${data.status||''}`}>
  {def.inputs.map((h,i)=><Handle key={h} type="target" position={Position.Left} id={h} style={{top:`${(i+1)/(def.inputs.length+1)*100}%`}} />)}
  <div className="node-title"><b>{def.label}</b>{data.error&&<span title={data.error}>⚠</span>}</div>
  {data.type==='number'&&<input value={local} onChange={e=>{setLocal(e.target.value);set({value:e.target.value})}} type="number" step="any"/>}
  {data.type==='formula'&&<input value={local} onChange={e=>{setLocal(e.target.value);set({expression:e.target.value})}} placeholder="a * 2 + b"/>}
  {data.type==='display'&&<div className="value">{data.status==='blocked'?'Blocked: upstream error':data.valueOut??'—'}</div>}
  {data.type!=='display'&&data.type!=='number'&&data.type!=='formula'&&<div className="value">{data.valueOut??'—'}</div>}
  {data.type==='number'&&<div className="value">{data.valueOut??'—'}</div>}
  {def.output&&<Handle type="source" position={Position.Right} id="out"/>}
  {(data.status==='blocked'||data.error)&&<div className="status-text" title={data.error||'Fix the input error on an upstream node'}>{data.error||'Blocked by an upstream error'}</div>}
 </div>
}
const nodeTypes={custom:NodeCard};
function App(){
 const [nodes,setNodes,onNodesChange]=useNodesState([]),[edges,setEdges,onEdgesChange]=useEdgesState([]); const [simState,setSimState]=useState('idle'); const [graphId,setGraphId]=useState(null); const [saveState,setSaveState]=useState(''); const seq=useRef(0),abort=useRef(null),timer=useRef(null); const rf=useReactFlow();
 const updateNodeData=useCallback((id,patch)=>setNodes(ns=>ns.map(n=>n.id===id?{...n,data:{...n.data,...patch}}:n)),[setNodes]);
 const decorate=useCallback(ns=>ns.map(n=>({...n,type:'custom',data:{...n.data,onChange:updateNodeData}})),[updateNodeData]);
 const addNode=type=>{const id=`${type}-${Date.now()}-${Math.random().toString(16).slice(2,6)}`; const p=rf.screenToFlowPosition({x:220+Math.random()*500,y:120+Math.random()*350}); const d={type,value:type==='number'?'1':'',expression:type==='formula'?'a + b':''};setNodes(ns=>[...ns,{id,type:'custom',position:p,data:{...d,onChange:updateNodeData}}])};
 const onConnect=useCallback(c=>{if(!c.source||!c.target||c.source===c.target)return; if(c.targetHandle==='out')return; setEdges(es=>{if(es.some(e=>e.target===c.target&&e.targetHandle===c.targetHandle))return es;return addEdge({...c,type:'smoothstep'},es)})},[setEdges]);
 const graph=useMemo(()=>({nodes:nodes.map(n=>({id:n.id,type:n.data.type,data:{...n.data,onChange:undefined,status:undefined,error:undefined,valueOut:undefined}})),edges}),[nodes,edges]);
 const graphJSON=JSON.stringify(graph); // Stable across simulation-result/status updates.
 const run=useCallback(async()=>{const my=++seq.current; abort.current?.abort(); const controller=new AbortController(); abort.current=controller;setSimState('running');
  try{const r=await fetch(`${API}/simulate`,{method:'POST',headers:{'content-type':'application/json'},body:graphJSON,signal:controller.signal});const body=await readApiJSON(r);if(my!==seq.current)return; if(body.status==='service_error'){setSimState('service_error');setSaveState(body.message||'Simulator unavailable');return}
   if(body.status==='error'){const errors=new Map((body.errors||[]).filter(x=>x.nodeId).map(x=>[x.nodeId,x.message])); const bad=new Set(errors.keys());
    // downstream blocking
    const blocked=new Set(bad); let changed=true; while(changed){changed=false; for(const e of edges){if(blocked.has(e.source)&&!blocked.has(e.target)){blocked.add(e.target);changed=true}}}
    setNodes(ns=>ns.map(n=>{const err=errors.get(n.id); return {...n,data:{...n.data,status:err?'error':blocked.has(n.id)?'blocked':'ok',error:err||null,valueOut:err||blocked.has(n.id)?null:n.data.valueOut}}}));setSimState('error');setSaveState(body.message||'Check node connections');return;}
   setNodes(ns=>ns.map(n=>({...n,data:{...n.data,status:'ok',error:null,valueOut:body.nodeValues?.[n.id]}})));setSimState('ok');setSaveState('');
  }catch(e){if(e.name!=='AbortError'&&my===seq.current){setSimState('service_error');setSaveState(e.message||'Simulation request failed')}}
 },[graphJSON,edges,setNodes]);
 useEffect(()=>{clearTimeout(timer.current);timer.current=setTimeout(run,300);return()=>clearTimeout(timer.current)},[graphJSON,run]);
 const save=async()=>{setSaveState('saving');try{let r;if(graphId)r=await fetch(`${API}/graphs/${graphId}`,{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({name:'My Graph',...graph})});else r=await fetch(`${API}/graphs`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:'My Graph',...graph})});const b=await readApiJSON(r);setGraphId(b._id);setSaveState('saved')}catch(e){setSaveState('save failed')}};
 const load=async()=>{if(!graphId)return;const r=await fetch(`${API}/graphs/${graphId}`);const b=await readApiJSON(r);setNodes(decorate(b.nodes||[]));setEdges(b.edges||[])};
 return <div className="app"><header><div><h1>Live Node Graph</h1><span>React Flow → Express → FastAPI → ngspice</span></div><div className="actions"><button onClick={save}>Save</button><button onClick={load} disabled={!graphId}>Load</button><span className={`sim ${simState}`}>{simState}</span>{saveState&&<span>{saveState}</span>}</div></header><aside><h3>Palette</h3>{Object.entries(defs).map(([k,v])=><button key={k} onClick={()=>addNode(k)}>＋ {v.label}</button>)}<hr/><small>Connect output → input. Each input accepts one wire. Delete selected nodes/edges with Backspace.</small></aside><main><ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} nodeTypes={nodeTypes} fitView deleteKeyCode={['Backspace','Delete']}><Background/><MiniMap/><Controls/></ReactFlow></main></div>
}
createRoot(document.getElementById('root')).render(<ReactFlowProvider><App/></ReactFlowProvider>);
