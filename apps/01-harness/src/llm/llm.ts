import { createHash } from 'node:crypto';
import { canonicalJson } from '@substrate/substrate';

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  temperature?: number;
}

export interface ToolCallSpec {
  name: string;
  args: unknown;
}

export interface ChatResponse {
  content: string;
  toolCalls: ToolCallSpec[];
}

export interface LLMProvider {
  complete(request: ChatRequest): Promise<ChatResponse>;
}

export interface RecordedCompletion {
  fingerprint: string;
  request: ChatRequest;
  response: ChatResponse;
}

export interface RecordingStore {
  get(fingerprint: string): Promise<RecordedCompletion | null>;
  set(completion: RecordedCompletion): Promise<void>;
  list(): Promise<RecordedCompletion[]>;
}

export function promptFingerprint(messages: ChatMessage[]): string {
  return createHash('sha256').update(canonicalJson(messages)).digest('hex');
}

export class MemoryRecordingStore implements RecordingStore {
  private map = new Map<string, RecordedCompletion>();
  async get(fingerprint: string): Promise<RecordedCompletion | null> {
    return this.map.get(fingerprint) ?? null;
  }
  async set(completion: RecordedCompletion): Promise<void> {
    this.map.set(completion.fingerprint, completion);
  }
  async list(): Promise<RecordedCompletion[]> {
    return [...this.map.values()];
  }
}

export class FileRecordingStore implements RecordingStore {
  constructor(private filePath: string) {}
  async get(fingerprint: string): Promise<RecordedCompletion | null> {
    const all = await this.list();
    return all.find((c) => c.fingerprint === fingerprint) ?? null;
  }
  async set(completion: RecordedCompletion): Promise<void> {
    const all = await this.list();
    all.push(completion);
    await writeLines(this.filePath, all);
  }
  async list(): Promise<RecordedCompletion[]> {
    try {
      const text = await readFile(this.filePath);
      return text
        .split('\n')
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l) as RecordedCompletion);
    } catch {
      return [];
    }
  }
}

function writeLines(filePath: string, lines: unknown[]): Promise<void> {
  return import('node:fs/promises').then((fs) =>
    fs.writeFile(filePath, lines.map((l) => JSON.stringify(l)).join('\n') + '\n', 'utf8'),
  );
}

function readFile(filePath: string): Promise<string> {
  return import('node:fs/promises').then((fs) => fs.readFile(filePath, 'utf8'));
}

export class RecordedLLM implements LLMProvider {
  rerolls = 0;
  misses = 0;
  constructor(
    private recording: RecordingStore,
    private delegate: LLMProvider,
    private replayOnly = false,
  ) {}

  async complete(request: ChatRequest): Promise<ChatResponse> {
    const fingerprint = promptFingerprint(request.messages);
    const recorded = await this.recording.get(fingerprint);
    if (recorded) return recorded.response;
    this.misses += 1;
    if (this.replayOnly) {
      throw new Error(`replay miss: no recorded completion for fingerprint ${fingerprint}`);
    }
    this.rerolls += 1;
    const response = await this.delegate.complete(request);
    await this.recording.set({ fingerprint, request, response });
    return response;
  }
}

export interface OpenAICompatOptions {
  baseUrl: string;
  model: string;
  apiKey?: string;
  fetchImpl?: typeof fetch;
}

export class OpenAICompatLLM implements LLMProvider {
  constructor(private opts: OpenAICompatOptions) {}

  async complete(request: ChatRequest): Promise<ChatResponse> {
    const url = `${this.opts.baseUrl.replace(/\/$/, '')}/chat/completions`;
    const fetchImpl = this.opts.fetchImpl ?? fetch;
    const res = await fetchImpl(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(this.opts.apiKey ? { authorization: `Bearer ${this.opts.apiKey}` } : {}),
      },
      body: JSON.stringify({
        model: this.opts.model,
        temperature: request.temperature ?? 0,
        messages: request.messages,
      }),
    });
    if (!res.ok) {
      throw new Error(`llm error ${res.status}: ${await res.text()}`);
    }
    const body = (await res.json()) as {
      choices?: Array<{
        message?: {
          content?: string | null;
          tool_calls?: Array<{ function?: { name?: string; arguments?: string } }>;
        };
      }>;
    };
    const message = body.choices?.[0]?.message;
    const toolCalls = (message?.tool_calls ?? []).map((tc) => {
      let args: unknown = {};
      try {
        args = JSON.parse(tc.function?.arguments ?? '{}') as unknown;
      } catch {
        args = {};
      }
      return { name: tc.function?.name ?? '', args };
    });
    return { content: message?.content ?? '', toolCalls };
  }
}

export function ollamaClient(opts?: Partial<OpenAICompatOptions>): OpenAICompatLLM {
  return new OpenAICompatLLM({
    baseUrl: opts?.baseUrl ?? 'http://localhost:11434/v1',
    model: opts?.model ?? 'qwen2.5:7b',
    fetchImpl: opts?.fetchImpl,
  });
}
