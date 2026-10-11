import express from 'express';
import cors from 'cors';
import mongoose from 'mongoose';

const app=express(); app.use(cors()); app.use(express.json({limit:'1mb'}));
const PORT=process.env.PORT||3000, MONGO_URL=process.env.MONGO_URL||'mongodb://localhost:27017/live_graph', SIM=process.env.SIMULATOR_URL||'http://localhost:8000';
const GraphSchema=new mongoose.Schema({name:{type:String,default:'Untitled'},nodes:{type:Array,default:[]},edges:{type:Array,default:[]}}, {timestamps:true});
const Graph=mongoose.model('Graph',GraphSchema);
app.get('/health',(req,res)=>res.json({ok:true}));
app.get('/api/graphs/:id',async(req,res)=>{try{const g=await Graph.findById(req.params.id).lean(); if(!g)return res.status(404).json({error:'Graph not found'}); res.json(g)}catch(e){res.status(400).json({error:e.message})}});
app.post('/api/graphs',async(req,res)=>{try{const g=await Graph.create({name:req.body.name||'Untitled',nodes:req.body.nodes||[],edges:req.body.edges||[]});res.status(201).json(g)}catch(e){res.status(400).json({error:e.message})}});
app.put('/api/graphs/:id',async(req,res)=>{try{const g=await Graph.findByIdAndUpdate(req.params.id,{name:req.body.name||'Untitled',nodes:req.body.nodes||[],edges:req.body.edges||[]},{new:true,runValidators:true}).lean();if(!g)return res.status(404).json({error:'Graph not found'});res.json(g)}catch(e){res.status(400).json({error:e.message})}});
app.post('/api/simulate',async(req,res)=>{try{const r=await fetch(`${SIM}/simulate`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(req.body),signal:AbortSignal.timeout(5500)});const body=await r.json();res.status(r.ok?200:502).json(body)}catch(e){res.status(503).json({status:'service_error',message:'Simulation service unavailable; edits will retry automatically',nodeValues:{},errors:[]})}});
await mongoose.connect(MONGO_URL);
app.listen(PORT,()=>console.log(`API listening on ${PORT}`));
