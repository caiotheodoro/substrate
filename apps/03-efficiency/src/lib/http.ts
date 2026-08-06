import { createServer, IncomingMessage, Server, ServerResponse } from 'node:http';

export type Handler = (
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
  body: unknown,
) => void | Promise<void>;

export interface Route {
  method: string;
  path: string;
  handler: Handler;
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) });
  res.end(payload);
}

export function sendText(res: ServerResponse, status: number, text: string): void {
  res.writeHead(status, { 'content-type': 'text/plain; charset=utf-8' });
  res.end(text);
}

export function readJson(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (raw.trim() === '') {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error('invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

/** Minimal JSON router over node:http — no framework dependency. */
export function jsonRouter(routes: Route[]): Server {
  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? '/', 'http://localhost');
      const route = routes.find((r) => r.method === req.method && r.path === url.pathname);
      if (!route) {
        sendJson(res, 404, { error: 'not found' });
        return;
      }
      const body = await readJson(req);
      await route.handler(req, res, url, body);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (!res.headersSent) sendJson(res, 500, { error: message });
      else res.end();
    }
  });
}

/** Bind and return the actual port (0 → ephemeral). Binds 0.0.0.0 for docker networking. */
export async function listen(server: Server, port: number): Promise<number> {
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '0.0.0.0', () => resolve());
  });
  const addr = server.address();
  if (addr === null || typeof addr === 'string') return port;
  return addr.port;
}

export function envPort(defaultPort: number): number {
  const raw = process.env.PORT;
  if (raw === undefined) return defaultPort;
  const n = Number.parseInt(raw, 10);
  return Number.isNaN(n) ? defaultPort : n;
}
