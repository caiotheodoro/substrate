import type { Stores, SandboxLease } from '../types';
import type { ExecOptions, SandboxTransport } from './transport';

export interface AcquireRequest {
  image: string;
  leaseMs?: number;
  name?: string;
  now?: () => string;
}

export interface SandboxManagerCoreOptions {
  stores: Stores;
  transport: SandboxTransport;
  idGen?: (prefix: string) => string;
  now?: () => string;
}

export class SandboxManagerCore {
  private stores: Stores;
  private transport: SandboxTransport;
  private idGen: (prefix: string) => string;
  private now: () => string;

  constructor(opts: SandboxManagerCoreOptions) {
    this.stores = opts.stores;
    this.transport = opts.transport;
    this.idGen = opts.idGen ?? ((p: string) => `${p}-${Math.random().toString(36).slice(2, 10)}`);
    this.now = opts.now ?? (() => new Date().toISOString());
  }

  async acquire(opts: AcquireRequest): Promise<SandboxLease> {
    const leaseMs = opts.leaseMs ?? 30000;
    const containerId = await this.transport.create(opts.image, opts.name ?? this.idGen('sb'));
    await this.transport.start(containerId);
    const lease: SandboxLease = {
      id: this.idGen('lease'),
      containerId,
      image: opts.image,
      leaseMs,
      expiresAt: new Date(Date.parse(this.now()) + leaseMs).toISOString(),
      updatedAt: this.now(),
      status: 'alive',
    };
    await this.stores.sandboxLeases.upsert(lease);
    return lease;
  }

  async keepalive(id: string): Promise<SandboxLease | null> {
    const lease = await this.stores.sandboxLeases.get(id);
    if (!lease) return null;
    if (this.isExpired(lease)) {
      await this.stores.sandboxLeases.upsert({ ...lease, status: 'expired' });
      return this.stores.sandboxLeases.get(id);
    }
    const renewed: SandboxLease = {
      ...lease,
      expiresAt: new Date(Date.parse(this.now()) + lease.leaseMs).toISOString(),
      updatedAt: this.now(),
      status: 'alive',
    };
    await this.stores.sandboxLeases.upsert(renewed);
    return renewed;
  }

  async liveness(id: string): Promise<{ alive: boolean; info: { running: boolean } }> {
    const lease = await this.stores.sandboxLeases.get(id);
    if (!lease) return { alive: false, info: { running: false } };
    try {
      const info = await this.transport.inspect(lease.containerId);
      const alive = info.running;
      await this.stores.sandboxLeases.upsert({ ...lease, status: alive ? 'alive' : 'expired', updatedAt: this.now() });
      return { alive, info: { running: info.running } };
    } catch {
      await this.stores.sandboxLeases.upsert({ ...lease, status: 'expired', updatedAt: this.now() });
      return { alive: false, info: { running: false } };
    }
  }

  async exec(id: string, cmd: string[], opts?: ExecOptions): Promise<{ exitCode: number; stdout: string; stderr: string }> {
    const lease = await this.stores.sandboxLeases.get(id);
    if (!lease) throw new Error(`no lease ${id}`);
    const live = await this.liveness(id);
    if (!live.alive) throw new Error('sandbox is not alive');
    return this.transport.exec(lease.containerId, cmd, opts);
  }

  async putArtifact(id: string, path: string, data: Buffer): Promise<void> {
    const lease = await this.stores.sandboxLeases.get(id);
    if (!lease) throw new Error(`no lease ${id}`);
    await this.transport.putArtifact(lease.containerId, path, data);
  }

  async getArtifact(id: string, path: string): Promise<Buffer> {
    const lease = await this.stores.sandboxLeases.get(id);
    if (!lease) throw new Error(`no lease ${id}`);
    return this.transport.getArtifact(lease.containerId, path);
  }

  async release(id: string): Promise<void> {
    const lease = await this.stores.sandboxLeases.get(id);
    if (!lease) return;
    await this.transport.remove(lease.containerId);
    await this.stores.sandboxLeases.remove(id);
  }

  async reapExpired(now = this.now()): Promise<string[]> {
    const leases = await this.stores.sandboxLeases.list();
    const reaped: string[] = [];
    for (const lease of leases) {
      if (Date.parse(lease.expiresAt) <= Date.parse(now)) {
        await this.release(lease.id);
        reaped.push(lease.id);
      }
    }
    return reaped;
  }

  private isExpired(lease: SandboxLease): boolean {
    return Date.parse(lease.expiresAt) <= Date.parse(this.now());
  }
}

export interface AcquireRequest {
  image: string;
  leaseMs?: number;
  name?: string;
}