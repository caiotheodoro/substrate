import { mulberry32 } from '../lib/rng.js';
import { diff, opsBytes, type PatchOp } from '../wire/delta-protocol.js';
import type { UiNode } from '../wire/render-ui-toy.js';
import { isMainModule } from '../lib/paths.js';

/**
 * A-E-32 delta-100th-turn-bench — does the follow-up delta saving survive
 * to turn 100, and where does "squash to full state" become cheaper than
 * continuing patches? Pure in-memory and fast: a UI tree mutates one node
 * at a time for 100 turns; turn 1 ships the full payload, follow-ups ship
 * RFC 6902 ops. The bench reports cumulative full-vs-delta bytes and the
 * squash crossover turn (first turn where shipping the full state is
 * cheaper than shipping the patch).
 */

export interface DeltaBenchResult {
  turns: number;
  cumulativeFullBytes: number;
  cumulativeDeltaBytes: number;
  reductionPct: number;
  squashCrossoverTurn: number | null;
  squashCount: number;
  nodeCount: number;
}

function makeTree(rng: () => number, size: number): UiNode {
  const root: UiNode = { type: 'div', props: {}, children: [] };
  const tags = ['text', 'button', 'input', 'span', 'div'];
  let count = 1;
  while (count < size) {
    const nodes: UiNode[] = [];
    const walk = (n: UiNode): void => {
      nodes.push(n);
      for (const c of n.children) walk(c);
    };
    walk(root);
    const parent = nodes[Math.floor(rng() * nodes.length)]!;
    const type = tags[Math.floor(rng() * tags.length)]!;
    const props: Record<string, string> = {};
    if (rng() < 0.5) props['class'] = `c${Math.floor(rng() * 12)}`;
    if (type === 'text') props['value'] = `v${Math.floor(rng() * 100)}`;
    parent.children.push({ type, props, children: [] });
    count++;
  }
  return root;
}

function countNodes(node: UiNode): number {
  return 1 + node.children.reduce((sum, c) => sum + countNodes(c), 0);
}

function mutate(rng: () => number, tree: UiNode): UiNode {
  const nodes: UiNode[] = [];
  const walk = (n: UiNode): void => {
    nodes.push(n);
    for (const c of n.children) walk(c);
  };
  walk(tree);
  const target = nodes[Math.floor(rng() * nodes.length)]!;
  const roll = rng();
  if (roll < 0.4) {
    target.props['class'] = `c${Math.floor(rng() * 20)}`;
    if (target.type === 'text') target.props['value'] = `v${Math.floor(rng() * 200)}`;
  } else if (roll < 0.7) {
    const idx = Math.floor(rng() * (target.children.length + 1));
    target.children.splice(idx, 0, {
      type: 'text',
      props: { value: `v${Math.floor(rng() * 200)}` },
      children: [],
    });
  } else if (target.children.length > 0) {
    target.children.splice(Math.floor(rng() * target.children.length), 1);
  }
  return tree;
}

export function runDeltaHundredTurnBench(opts: { turns?: number; seed?: number; nodeCount?: number } = {}): DeltaBenchResult {
  const turns = opts.turns ?? 100;
  const seed = opts.seed ?? 99;
  const targetNodes = opts.nodeCount ?? 40;
  const rng = mulberry32(seed);
  let tree = makeTree(rng, targetNodes);

  let cumulativeFullBytes = 0;
  let cumulativeDeltaBytes = 0;
  let squashCrossoverTurn: number | null = null;
  let squashCount = 0;
  let opsSinceFull: PatchOp[] = [];

  for (let turn = 1; turn <= turns; turn++) {
    const fullBytes = Buffer.byteLength(JSON.stringify(tree), 'utf8');
    cumulativeFullBytes += fullBytes;

    if (turn === 1) {
      opsSinceFull = [];
      continue;
    }

    const next = mutate(rng, structuredClone(tree));
    const ops = diff(tree, next);
    tree = next;

    const deltaThisTurn = opsBytes(ops);
    opsSinceFull = opsSinceFull.concat(ops);
    const accumulatedDelta = Buffer.byteLength(JSON.stringify(opsSinceFull), 'utf8');

    if (opsSinceFull.length > 0 && accumulatedDelta > fullBytes) {
      // Squash: ship the full snapshot instead of the accumulated patch.
      cumulativeDeltaBytes += fullBytes;
      squashCount++;
      if (squashCrossoverTurn === null) squashCrossoverTurn = turn;
      opsSinceFull = [];
    } else {
      cumulativeDeltaBytes += deltaThisTurn;
    }
  }

  return {
    turns,
    cumulativeFullBytes,
    cumulativeDeltaBytes,
    reductionPct: cumulativeFullBytes === 0 ? 0 : (1 - cumulativeDeltaBytes / cumulativeFullBytes) * 100,
    squashCrossoverTurn,
    squashCount,
    nodeCount: countNodes(tree),
  };
}

export function printDeltaBench(result: DeltaBenchResult): string {
  return [
    `delta-100th-turn bench (${result.turns} turns, ${result.nodeCount} nodes)`,
    `  full payload total: ${result.cumulativeFullBytes} bytes`,
    `  delta total:        ${result.cumulativeDeltaBytes} bytes`,
    `  reduction:          ${result.reductionPct.toFixed(1)}%`,
    `  squash crossover:   turn ${result.squashCrossoverTurn ?? 'never'}`,
    `  squashes triggered: ${result.squashCount}`,
  ].join('\n');
}

export async function main(argv: string[]): Promise<number> {
  const turns = Number(argv[0] ?? 100);
  const result = runDeltaHundredTurnBench({ turns });
  process.stdout.write(printDeltaBench(result) + '\n');
  return 0;
}

if (isMainModule(import.meta.url)) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}
