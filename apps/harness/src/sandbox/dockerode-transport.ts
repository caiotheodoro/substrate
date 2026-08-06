import Dockerode from 'dockerode';
import type { ContainerInfo, ExecResult, ExecOptions, SandboxTransport } from './transport';

export class DockerodeTransport implements SandboxTransport {
  private docker: Dockerode;

  constructor(socketPath = '/var/run/docker.sock') {
    this.docker = new Dockerode({ socketPath });
  }

  async create(image: string, name: string): Promise<string> {
    const container = await this.docker.createContainer({ Image: image, name, Tty: false });
    return container.id;
  }

  async start(id: string): Promise<void> {
    await this.docker.getContainer(id).start();
  }

  async exec(id: string, cmd: string[], opts?: ExecOptions): Promise<ExecResult> {
    const timeoutMs = opts?.timeoutMs ?? 15000;
    const maxOutputBytes = opts?.maxOutputBytes ?? 64 * 1024;
    const exec = await this.docker.getContainer(id).exec({
      Cmd: cmd,
      AttachStdout: true,
      AttachStderr: true,
    });
    const stream = await exec.start({});
    let stdout = '';
    let stderr = '';
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        stream.destroy();
        reject(new Error(`sandbox exec timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      stream.on('data', (chunk: Buffer) => {
        const text = chunk.toString('utf8');
        if (stdout.length + text.length <= maxOutputBytes) stdout += text;
        else stdout += text.slice(0, maxOutputBytes - stdout.length);
      });
      stream.on('end', () => {
        clearTimeout(timer);
        resolve();
      });
      stream.on('error', (err) => {
        clearTimeout(timer);
        reject(err);
      });
    });
    const info = await exec.inspect();
    return { exitCode: info.ExitCode ?? -1, stdout, stderr };
  }

  async inspect(id: string): Promise<ContainerInfo> {
    const info = await this.docker.getContainer(id).inspect();
    return { running: Boolean(info.State?.Running), startedAt: info.State?.StartedAt ?? null };
  }

  async remove(id: string): Promise<void> {
    try {
      await this.docker.getContainer(id).remove({ force: true });
    } catch {
      return;
    }
  }

  async putArtifact(id: string, path: string, data: Buffer): Promise<void> {
    const container = this.docker.getContainer(id);
    const archive = tarFromBuffer(data);
    await container.putArchive(archive, { path });
  }

  async getArtifact(id: string, path: string): Promise<Buffer> {
    const container = this.docker.getContainer(id);
    const archive = await container.getArchive({ path });
    const chunks: Buffer[] = [];
    for await (const chunk of archive as unknown as AsyncIterable<Buffer>) chunks.push(chunk);
    return Buffer.concat(chunks);
  }
}

function tarFromBuffer(data: Buffer): Buffer {
  const header = Buffer.alloc(512);
  header.write('data.bin', 0, 8, 'utf8');
  header.writeUInt32BE(data.length, 100 + 32);
  header.writeUInt32BE(0o644, 100);
  header.write('100644', 100, 8, 'utf8');
  header.write('00000000000000', 108, 14, 'utf8');
  header.write('00000000000000', 124, 14, 'utf8');
  header.write('00000000', 136, 8, 'utf8');
  header.write('ustar', 257, 5, 'utf8');
  header.write('00', 262, 2, 'utf8');
  const body = data.length % 512 === 0 ? data : Buffer.concat([data, Buffer.alloc(512 - (data.length % 512))]);
  const padding = Buffer.alloc(1024);
  return Buffer.concat([header, body, padding]);
}
