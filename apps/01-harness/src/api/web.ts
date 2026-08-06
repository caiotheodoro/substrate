import type { Express } from 'express';
import express from 'express';

export function createWebApp(apiBaseUrl = 'http://localhost:8930'): Express {
  const app = express();

  app.get('/', (_req, res) => res.type('html').send(webHtml(apiBaseUrl)));

  app.get('/runs/:id', (_req, res) => res.type('html').send(runHtml(apiBaseUrl)));

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  return app;
}

function webHtml(apiBaseUrl: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>Harness — read-only transcript</title>
<style>body{font-family:system-ui;margin:2rem;max-width:960px} .ev{border-bottom:1px solid #eee;padding:.5rem 0;white-space:pre-wrap;font-size:.85rem} h1{font-size:1.4rem}</style>
</head><body><h1>Harness transcript (read-only)</h1><ul id="runs"></ul>
<script>
const API='${apiBaseUrl}';
async function load(){const r=await fetch(API+'/runs');const b=await r.json();
 const ul=document.getElementById('runs');ul.innerHTML='';
 b.runs.forEach(x=>{const li=document.createElement('li');
  const a=document.createElement('a');a.href='/runs/'+x.id;a.textContent=x.id+' — '+(x.task||'').slice(0,60)+' ('+x.status+')';
  li.appendChild(a);ul.appendChild(li);});}
load();
</script></body></html>`;
}

function runHtml(apiBaseUrl: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>Run transcript</title>
<style>body{font-family:system-ui;margin:2rem;max-width:960px} .ev{border-bottom:1px solid #eee;padding:.5rem 0;white-space:pre-wrap;font-size:.85rem}</style>
</head><body><h1 id="title">Run</h1><div id="events"></div>
<script>
const API='${apiBaseUrl}';
const runId=location.pathname.split('/').pop();
document.getElementById('title').textContent='Run '+runId;
async function load(){const r=await fetch(API+'/runs/'+runId+'/events');const b=await r.json();
 const root=document.getElementById('events');root.innerHTML='';
 b.events.forEach(e=>{const div=document.createElement('div');div.className='ev';
  div.textContent=e.seq+'\t'+e.family+'\t'+(e.kind??'')+'\t'+JSON.stringify(e.payload??e.result??'');
  root.appendChild(div);});}
load();
const es=new EventSource(API+'/runs/'+runId+'/events/stream');
es.onmessage=()=>load();
</script></body></html>`;
}
