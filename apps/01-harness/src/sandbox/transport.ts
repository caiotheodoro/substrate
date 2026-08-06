export interface ExecOptions {
  timeoutMs?: number;
  maxOutputBytes?: number;
}

export interface ExecResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

export interface ContainerInfo {
  running: boolean;
  startedAt: string | null;
}

export interface SandboxTransport {
  create(image: string, name: string): Promise<string>;
  start(id: string): Promise<void>;
  exec(id: string, cmd: string[], opts?: ExecOptions): Promise<ExecResult>;
  inspect(id: string): Promise<ContainerInfo>;
  remove(id: string): Promise<void>;
  putArtifact(id: string, path: string, data: Buffer): Promise<void>;
  getArtifact(id: string, path: string): Promise<Buffer>;
}
