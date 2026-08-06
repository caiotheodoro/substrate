import type { ContainerInfo, ExecResult, SandboxTransport } from './transport';

export interface MemoryContainer {
  id: string;
  image: string;
  running: boolean;
  startedAt: string | null;
  artifacts: Map<string, Buffer>;
  dead: boolean;
}

export class MemoryTransport implements SandboxTransport {
  private containers = new Map<string, MemoryContainer>();
  private commandTable: Array<{
    image: string;
    matches: (cmd: string[]) => boolean;
    run: (cmd: string[], container: MemoryContainer) => ExecResult;
  }> = [];

  seed(image: string, cmd: string[], result: ExecResult): void {
    this.commandTable.push({
      image,
      matches: (c) => c.join(' ') === cmd.join(' '),
      run: () => result,
    });
  }

  failOn(image: string, cmdPrefix: string, times: number): void {
    let remaining = times;
    this.commandTable.push({
      image,
      matches: (c) => c[0] === cmdPrefix,
      run: () => {
        if (remaining > 0) {
          remaining -= 1;
          return { exitCode: 1, stdout: '', stderr: 'transient sandbox failure' };
        }
        return { exitCode: 0, stdout: 'ok', stderr: '' };
      },
    });
  }

  listContainers(): MemoryContainer[] {
    return [...this.containers.values()];
  }

  kill(id: string): void {
    const c = this.containers.get(id);
    if (c) {
      c.running = false;
      c.dead = true;
    }
  }

  async create(image: string, name: string): Promise<string> {
    const id = `${name}-${this.containers.size + 1}`;
    this.containers.set(id, { id, image, running: false, startedAt: null, artifacts: new Map(), dead: false });
    return id;
  }

  async start(id: string): Promise<void> {
    const c = this.containers.get(id);
    if (!c) throw new Error(`no container ${id}`);
    c.running = true;
    c.startedAt = new Date().toISOString();
  }

  async exec(id: string, cmd: string[], _opts?: unknown): Promise<ExecResult> {
    const c = this.containers.get(id);
    if (!c) throw new Error(`no container ${id}`);
    if (c.dead) throw new Error('container is dead');
    const handler = this.commandTable.find((h) => h.image === c.image && h.matches(cmd));
    if (handler) return handler.run(cmd, c);
    return { exitCode: 0, stdout: `exec: ${cmd.join(' ')}`, stderr: '' };
  }

  async inspect(id: string): Promise<ContainerInfo> {
    const c = this.containers.get(id);
    if (!c) throw new Error(`no container ${id}`);
    return { running: c.running && !c.dead, startedAt: c.startedAt };
  }

  async remove(id: string): Promise<void> {
    this.containers.delete(id);
  }

  async putArtifact(id: string, path: string, data: Buffer): Promise<void> {
    const c = this.containers.get(id);
    if (!c) throw new Error(`no container ${id}`);
    c.artifacts.set(path, data);
  }

  async getArtifact(id: string, path: string): Promise<Buffer> {
    const c = this.containers.get(id);
    const data = c?.artifacts.get(path);
    if (!data) throw new Error(`no artifact ${path}`);
    return data;
  }
}
