import type { SandboxLease } from '../types';
import type { ExecOptions } from './transport';

export interface SandboxClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
}

export class SandboxClient {
  private baseUrl: string;
  private fetchImpl: typeof fetch;

  constructor(opts: SandboxClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  async acquire(image: string, leaseMs?: number): Promise<SandboxLease> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ image, leaseMs }),
    });
    assertOk(res);
    const body = (await res.json()) as { lease: SandboxLease };
    return body.lease;
  }

  async keepalive(id: string): Promise<SandboxLease> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes/${id}/keepalive`, { method: 'POST' });
    assertOk(res);
    const body = (await res.json()) as { lease: SandboxLease };
    return body.lease;
  }

  async liveness(id: string): Promise<{ alive: boolean }> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes/${id}/liveness`);
    assertOk(res);
    const body = (await res.json()) as { alive: boolean };
    return { alive: body.alive };
  }

  async exec(id: string, cmd: string[], opts?: ExecOptions): Promise<{ exitCode: number; stdout: string; stderr: string }> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes/${id}/exec`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ cmd, opts }),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      throw new Error(body.error ?? `sandbox exec failed: ${res.status}`);
    }
    const body = (await res.json()) as { result: { exitCode: number; stdout: string; stderr: string } };
    return body.result;
  }

  async putArtifact(id: string, path: string, data: Buffer): Promise<void> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes/${id}/artifacts`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path, data: data.toString('base64') }),
    });
    assertOk(res);
  }

  async getArtifact(id: string, path: string): Promise<Buffer> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes/${id}/artifacts?path=${encodeURIComponent(path)}`);
    assertOk(res);
    const body = (await res.json()) as { data: string };
    return Buffer.from(body.data, 'base64');
  }

  async release(id: string): Promise<void> {
    const res = await this.fetchImpl(`${this.baseUrl}/sandboxes/${id}`, { method: 'DELETE' });
    assertOk(res);
  }
}

export function assertOk(res: { ok: boolean; status: number }): void {
  if (!res.ok) throw new Error(`sandbox client error: ${res.status}`);
}
