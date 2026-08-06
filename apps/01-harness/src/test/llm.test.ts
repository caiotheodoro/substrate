import { describe, expect, it } from 'vitest';
import {
  FileRecordingStore,
  MemoryRecordingStore,
  OpenAICompatLLM,
  RecordedLLM,
  ollamaClient,
  promptFingerprint,
} from '../llm/llm';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function fakeFetch(responses: Array<{ ok: boolean; json: () => Promise<unknown>; text?: () => Promise<string> }>): typeof fetch {
  const queue = [...responses];
  return (async () => {
    const next = queue.shift();
    if (!next) throw new Error('no more fake responses');
    return {
      ok: next.ok,
      json: next.json,
      text: next.text ?? (async () => ''),
      status: next.ok ? 200 : 500,
    } as unknown as Response;
  }) as unknown as typeof fetch;
}

describe('RecordedLLM', () => {
  it('records on first encounter and replays without rerolls', async () => {
    const store = new MemoryRecordingStore();
    let delegateCalls = 0;
    const llm = new RecordedLLM(store, {
      complete: async () => {
        delegateCalls += 1;
        return { content: 'hello', toolCalls: [] };
      },
    });
    const request = { messages: [{ role: 'user' as const, content: 'hi' }] };
    const first = await llm.complete(request);
    expect(first.content).toBe('hello');
    expect(llm.rerolls).toBe(1);
    expect(llm.misses).toBe(1);
    const second = await llm.complete(request);
    expect(second.content).toBe('hello');
    expect(delegateCalls).toBe(1);
    expect(llm.misses).toBe(1);
    expect(llm.rerolls).toBe(1);
  });

  it('replay-only mode throws on unknown fingerprints', async () => {
    const store = new MemoryRecordingStore();
    await store.set({
      fingerprint: promptFingerprint([{ role: 'user', content: 'known' }]),
      request: { messages: [{ role: 'user', content: 'known' }] },
      response: { content: 'ok', toolCalls: [] },
    });
    const llm = new RecordedLLM(store, {
      complete: async () => ({ content: 'never', toolCalls: [] }),
    }, true);
    const ok = await llm.complete({ messages: [{ role: 'user', content: 'known' }] });
    expect(ok.content).toBe('ok');
    await expect(llm.complete({ messages: [{ role: 'user', content: 'unknown' }] })).rejects.toThrow('replay miss');
    expect(llm.misses).toBe(1);
  });

  it('promptFingerprint is stable under key order but changes with content', () => {
    const a = promptFingerprint([
      { role: 'system', content: 'x' },
      { role: 'user', content: 'y' },
    ]);
    const b = promptFingerprint([
      { content: 'x', role: 'system' },
      { content: 'y', role: 'user' },
    ]);
    expect(a).toBe(b);
    const c = promptFingerprint([{ role: 'system', content: 'x' }, { role: 'user', content: 'z' }]);
    expect(c).not.toBe(a);
  });
});

describe('FileRecordingStore', () => {
  it('persists and reloads recorded completions', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'harness-llm-'));
    const path = join(dir, 'rec.jsonl');
    const store = new FileRecordingStore(path);
    await store.set({
      fingerprint: 'fp1',
      request: { messages: [{ role: 'user', content: 'a' }] },
      response: { content: 'r1', toolCalls: [] },
    });
    await store.set({
      fingerprint: 'fp2',
      request: { messages: [{ role: 'user', content: 'b' }] },
      response: { content: 'r2', toolCalls: [] },
    });
    const reloaded = new FileRecordingStore(path);
    const all = await reloaded.list();
    expect(all).toHaveLength(2);
    const got = await reloaded.get('fp1');
    expect(got?.response.content).toBe('r1');
    const raw = readFileSync(path, 'utf8');
    expect(raw.trimEnd().split('\n')).toHaveLength(2);
  });

  it('returns empty list when the file does not exist', async () => {
    const store = new FileRecordingStore('/nonexistent/dir/nope.jsonl');
    expect(await store.list()).toEqual([]);
  });
});

describe('OpenAICompatLLM', () => {
  it('parses chat completions with tool calls', async () => {
    const llm = new OpenAICompatLLM({
      baseUrl: 'http://fake:1/v1',
      model: 'test-model',
      fetchImpl: fakeFetch([
        {
          ok: true,
          json: async () => ({
            choices: [
              {
                message: {
                  content: 'using tool',
                  tool_calls: [{ function: { name: 'echo', arguments: '{"text":"x"}' } }],
                },
              },
            ],
          }),
        },
      ]),
    });
    const res = await llm.complete({ messages: [{ role: 'user', content: 'go' }] });
    expect(res.content).toBe('using tool');
    expect(res.toolCalls).toEqual([{ name: 'echo', args: { text: 'x' } }]);
  });

  it('handles HTTP errors', async () => {
    const llm = new OpenAICompatLLM({
      baseUrl: 'http://fake:1/v1',
      model: 'm',
      fetchImpl: fakeFetch([{ ok: false, json: async () => ({}), text: async () => 'boom' }]),
    });
    await expect(llm.complete({ messages: [] })).rejects.toThrow('llm error');
  });

  it('ollamaClient builds an OpenAI-compatible provider against localhost', () => {
    const client = ollamaClient({ fetchImpl: async () => new Response('') });
    expect(client).toBeInstanceOf(OpenAICompatLLM);
  });
});
