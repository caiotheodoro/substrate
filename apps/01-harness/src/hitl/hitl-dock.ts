import type { Express } from 'express';
import express from 'express';
import { WebSocketServer, WebSocket } from 'ws';
import type { Server } from 'node:http';
import type { PendingAction, Stores } from '../types';
import { atomicResolve, allReady, requiredFields } from './pending-action';

export function createDockApp(stores: Stores): Express {
  const app = express();
  app.use(express.json());

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  app.get('/actions', async (req, res) => {
    const runId = String(req.query.runId ?? '');
    const actions = runId ? await stores.pendingActions.list(runId) : await allActions(stores);
    res.json({ actions, allReady: allReady(actions) });
  });

  app.get('/actions/:id', async (req, res) => {
    const action = await stores.pendingActions.get(req.params.id);
    if (!action) return res.status(404).json({ error: 'not found' });
    res.json({ action, required: requiredFields(action.schema) });
  });

  app.post('/actions/:id/answer', async (req, res) => {
    const { answer, by } = req.body as { answer: Record<string, unknown>; by?: string };
    const action = await stores.pendingActions.get(req.params.id);
    if (!action) return res.status(404).json({ error: 'not found' });
    await stores.pendingActions.resolve(action.id, answer ?? {}, by ?? 'human');
    res.json({ action: await stores.pendingActions.get(action.id) });
  });

  app.post('/actions/atomic', async (req, res) => {
    const { ids, answers, by } = req.body as {
      ids: string[];
      answers: Record<string, Record<string, unknown>>;
      by?: string;
    };
    const resolved = await atomicResolve(stores, ids ?? [], answers ?? {}, by ?? 'human');
    res.json({ resolved, allReady: allReady(resolved) });
  });

  return app;
}

export function createDockServer(stores: Stores, port = 8938): { server: Server; ws: WebSocketServer } {
  const app = createDockApp(stores);
  const server = app.listen(port);
  const ws = new WebSocketServer({ server, path: '/ws' });
  const seen = new Set<string>();
  const unsubscribe = stores.emit.on((e) => {
    if (e.family === 'stream' && e.kind === 'pending.action.requested') {
      const payload = e.payload as { actionId: string };
      if (seen.has(payload.actionId)) return;
      seen.add(payload.actionId);
      ws.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
          client.send(JSON.stringify({ type: 'action.requested', actionId: payload.actionId }));
        }
      });
    }
  });
  server.on('close', unsubscribe);
  return { server, ws };
}

async function allActions(stores: Stores): Promise<PendingAction[]> {
  const runs = await stores.runs.list();
  const out: PendingAction[] = [];
  for (const r of runs) {
    const actions = await stores.pendingActions.list(r.id);
    out.push(...actions);
  }
  return out;
}

export function dockHtml(): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>HITL Dock</title>
<style>body{font-family:system-ui;margin:2rem;max-width:720px} .action{border:1px solid #ccc;border-radius:8px;padding:1rem;margin-bottom:1rem} input,select{display:block;margin:.4rem 0;width:100%} button{padding:.5rem 1rem} .ready{color:green;font-weight:600}</style>
</head><body>
<h1>HITL Dock</h1><p class="ready" id="gate">all-ready gate: pending</p><div id="actions"></div>
<script>
const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
let actions=[];
ws.onmessage=(ev)=>{const m=JSON.parse(ev.data);if(m.type==='action.requested')refresh();};
async function refresh(){const r=await fetch('/actions');const body=await r.json();actions=body.actions;render();}
function render(){
  const gate=document.getElementById('gate');
  gate.textContent=bodySafe(actions);
  const root=document.getElementById('actions');root.innerHTML='';
  const pending=actions.filter(a=>a.status==='pending');
  gate.textContent='all-ready gate: '+pending.length+' pending';
  pending.forEach(a=>{const div=document.createElement('div');div.className='action';
    div.innerHTML='<b>'+esc(a.kind)+'</b>: '+esc(a.prompt)+'<br>'+formFields(a)+'<button data-id="'+a.id+'">Submit</button>';
    root.appendChild(div);});
  root.querySelectorAll('button').forEach(b=>b.onclick=async()=>{
    const div=b.parentElement;const answer={};
    div.querySelectorAll('[data-field]').forEach(inp=>answer[inp.dataset.field]=inp.value);
    await fetch('/actions/'+b.dataset.id+'/answer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({answer,by:'human'})});
    refresh();
  });
}
function formFields(a){const s=a.schema||{};const props=s.properties||{};
  return Object.keys(props).map(k=>'<input data-field="'+k+'" placeholder="'+k+'">').join('');}
function bodySafe(actions){return actions.filter(a=>a.status==='pending').length+' pending';}
function esc(s){return String(s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));}
refresh();
</script></body></html>`;
}
