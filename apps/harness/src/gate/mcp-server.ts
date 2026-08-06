import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import { z } from 'zod';
import type { Stores } from '../types';
import type { ToolRunner } from '../engine/engine';
import type { GateCore } from '../gate/gate-core';

export interface GatedMcpOptions {
  stores: Stores;
  tools: ToolRunner;
  gate: GateCore;
  runId?: string;
  turn?: () => number;
  onDecision?: (record: {
    decisionId: string;
    name: string;
    verdict: string;
    score: number;
  }) => void;
}

export interface GatedMcpHandle {
  server: McpServer;
  connect(transport: Transport): Promise<void>;
  disconnect(): Promise<void>;
  decisionCount(): Promise<number>;
}

export function riskOf(name: string): number {
  const table: Record<string, number> = {
    echo: 0,
    'fake-clock': 0,
    delay: 0,
    httpbin: 0.1,
    'fail-once': 0.1,
    file: 0.4,
    'request_action': 0.2,
    refund: 0.9,
    approve: 0.85,
  };
  return table[name] ?? 0.3;
}

export function createGatedMcpServer(opts: GatedMcpOptions): GatedMcpHandle {
  const server = new McpServer(
    { name: 'substrate-gate', version: '0.1.0' },
    { capabilities: { tools: {} } },
  );
  let alive = true;

  for (const tool of opts.tools.list()) {
    server.registerTool(
      tool.name,
      {
        description: tool.description,
        inputSchema: z.record(z.string(), z.unknown()).optional() as unknown as z.ZodType<Record<string, unknown>>,
      },
      async (args: { [key: string]: unknown }) => {
        const features = {
          toolName: tool.name,
          toolOk: true,
          schemaValid: true,
          riskScore: riskOf(tool.name),
          evidenceScore: 0.5,
        };
        const decision = await opts.gate.decide(tool.name, features);
        await opts.stores.decisions.insert({
          decisionId: decision.decisionId,
          turnId: String(opts.turn?.() ?? 0),
          action: `${tool.name}:${decision.decisionId}`,
          confidenceFeatures: features,
          verdict: decision.verdict,
          outcome: null,
          confirmedAt: null,
        });
        opts.onDecision?.({
          decisionId: decision.decisionId,
          name: tool.name,
          verdict: decision.verdict,
          score: decision.score,
        });

        if (decision.verdict === 'reject') {
          return {
            content: [
              { type: 'text', text: `REJECTED by substrate gate (confidence ${decision.score.toFixed(3)}).` },
            ],
            isError: true,
          };
        }
        if (decision.verdict === 'escalate') {
          return {
            content: [
              {
                type: 'text',
                text: `ESCALATION_REQUIRED for ${tool.name} (confidence ${decision.score.toFixed(3)}): awaiting reviewer via request_action.`,
              },
            ],
            isError: true,
          };
        }
        const result = await tool.run(args as Record<string, unknown>);
        if (opts.runId) {
          const tail = await opts.stores.events.tail(opts.runId);
          await opts.stores.events.append(
            opts.runId,
            [
              {
                family: 'capture',
                toolCallId: decision.decisionId,
                result,
                attempt: 0,
                ts: new Date().toISOString(),
              },
            ],
            tail,
          );
        }
        return { content: [{ type: 'text', text: JSON.stringify(result) }] };
      },
    );
  }

  return {
    server,
    connect: async (transport) => {
      await server.connect(transport);
    },
    disconnect: async () => {
      if (alive) {
        await server.close();
        alive = false;
      }
    },
    decisionCount: async () => (await opts.stores.decisions.list()).length,
  };
}

export async function createLinkedClient(server: GatedMcpHandle): Promise<{
  client: import('@modelcontextprotocol/sdk/client/index.js').Client;
  keepAlive: () => void;
}> {
  const { Client } = await import('@modelcontextprotocol/sdk/client/index.js');
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client(
    { name: 'harness-client', version: '0.1.0' },
    { capabilities: {} },
  );
  await client.connect(clientTransport);
  return { client, keepAlive: () => undefined };
}