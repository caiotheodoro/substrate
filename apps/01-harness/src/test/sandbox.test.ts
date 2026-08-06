import { describe, expect, it } from 'vitest';
import { createMemoryStores } from '../db/memory';
import { SandboxManagerCore } from '../sandbox/manager';
import { MemoryTransport } from '../sandbox/memory-transport';

function manager(now: () => string) {
  const stores = createMemoryStores({ now });
  const transport = new MemoryTransport();
  let n = 0;
  const mgr = new SandboxManagerCore({
    stores,
    transport,
    now,
    idGen: (p) => `${p}-${++n}`,
  });
  return { mgr, stores, transport };
}

describe('SandboxManagerCore', () => {
  it('acquire creates a lease and a container, exec runs a seeded command', async () => {
    const { mgr, stores, transport } = manager(() => '2026-01-01T00:00:00.000Z');
    transport.seed('alpine:3.20', ['echo', 'hi'], { exitCode: 0, stdout: 'hi', stderr: '' });
    const lease = await mgr.acquire({ image: 'alpine:3.20', leaseMs: 30000 });
    expect(lease.status).toBe('alive');
    expect(lease.expiresAt).toBe('2026-01-01T00:00:30.000Z');
    const got = await stores.sandboxLeases.get(lease.id);
    expect(got?.containerId).toBe(lease.containerId);
    const exec = await mgr.exec(lease.id, ['echo', 'hi']);
    expect(exec).toEqual({ exitCode: 0, stdout: 'hi', stderr: '' });
  });

  it('keepalive extends the lease expiry', async () => {
    let now = '2026-01-01T00:00:00.000Z';
    const { mgr } = manager(() => now);
    const lease = await mgr.acquire({ image: 'alpine:3.20', leaseMs: 10000 });
    now = '2026-01-01T00:00:05.000Z';
    const kept = await mgr.keepalive(lease.id);
    expect(kept?.expiresAt).toBe('2026-01-01T00:00:15.000Z');
  });

  it('liveness reflects container running state', async () => {
    const { mgr, transport } = manager(() => '2026-01-01T00:00:00.000Z');
    const lease = await mgr.acquire({ image: 'alpine:3.20' });
    expect((await mgr.liveness(lease.id)).alive).toBe(true);
    transport.kill(lease.containerId);
    expect((await mgr.liveness(lease.id)).alive).toBe(false);
  });

  it('exec fails on a dead container', async () => {
    const { mgr, transport } = manager(() => '2026-01-01T00:00:00.000Z');
    const lease = await mgr.acquire({ image: 'alpine:3.20' });
    transport.kill(lease.containerId);
    await expect(mgr.exec(lease.id, ['echo', 'x'])).rejects.toThrow('not alive');
  });

  it('artifacts round-trip through the transport', async () => {
    const { mgr } = manager(() => '2026-01-01T00:00:00.000Z');
    const lease = await mgr.acquire({ image: 'alpine:3.20' });
    await mgr.putArtifact(lease.id, '/out/data.bin', Buffer.from('artifact'));
    const back = await mgr.getArtifact(lease.id, '/out/data.bin');
    expect(back.toString('utf8')).toBe('artifact');
  });

  it('reapExpired removes expired leases only', async () => {
    let now = '2026-01-01T00:00:00.000Z';
    const { mgr, stores } = manager(() => now);
    const a = await mgr.acquire({ image: 'alpine:3.20', leaseMs: 5000 });
    const b = await mgr.acquire({ image: 'alpine:3.20', leaseMs: 5000 });
    now = '2026-01-01T00:00:06.000Z';
    const reaped = await mgr.reapExpired();
    expect(reaped).toEqual(expect.arrayContaining([a.id, b.id]));
    expect(await stores.sandboxLeases.get(a.id)).toBeNull();
    expect(await stores.sandboxLeases.get(b.id)).toBeNull();
  });

  it('release removes the lease and container', async () => {
    const { mgr, stores } = manager(() => '2026-01-01T00:00:00.000Z');
    const lease = await mgr.acquire({ image: 'alpine:3.20' });
    await mgr.release(lease.id);
    expect(await stores.sandboxLeases.get(lease.id)).toBeNull();
  });

  it('keepalive on unknown lease returns null', async () => {
    const { mgr } = manager(() => '2026-01-01T00:00:00.000Z');
    expect(await mgr.keepalive('nope')).toBeNull();
  });
});
