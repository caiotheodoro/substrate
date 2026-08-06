import { describe, expect, it } from 'vitest';
import { canonicalJson } from '@substrate/substrate';
import {
  applyPatch,
  diff,
  opsBytes,
  parsePointer,
  squashToFull,
} from '../wire/delta-protocol.js';
import type { PatchOp } from '../wire/delta-protocol.js';
import { SchemaRegistry } from '../wire/schema-registry.js';
import { dslToTree, renderDeltas, treeToDsl, treeTokenEstimate } from '../wire/render-ui-toy.js';
import { assemblePrompt, cacheEligiblePrefix, makeBlock, stablePrefixBytes } from '../wire/instruction-blocks.js';

describe('A-E-20 delta-protocol — RFC 6902 apply', () => {
  it('applies add/remove/replace on objects and arrays', () => {
    expect(applyPatch({ a: 1 }, [{ op: 'add', path: '/b', value: 2 }])).toEqual({ a: 1, b: 2 });
    expect(applyPatch({ a: 1, b: 2 }, [{ op: 'remove', path: '/a' }])).toEqual({ b: 2 });
    expect(applyPatch({ a: 1 }, [{ op: 'replace', path: '/a', value: 9 }])).toEqual({ a: 9 });
    expect(applyPatch({ items: [1, 2] }, [{ op: 'add', path: '/items/1', value: 9 }])).toEqual({ items: [1, 9, 2] });
    expect(applyPatch({ items: [1, 2, 3] }, [{ op: 'remove', path: '/items/1' }])).toEqual({ items: [1, 3] });
    expect(applyPatch({ items: [1, 2] }, [{ op: 'add', path: '/items/-', value: 3 }])).toEqual({ items: [1, 2, 3] });
  });

  it('applies move and copy and validates with test', () => {
    expect(applyPatch({ a: 1, b: 2 }, [{ op: 'move', path: '/c', from: '/a' }])).toEqual({ b: 2, c: 1 });
    expect(applyPatch({ a: 1 }, [{ op: 'copy', path: '/b', from: '/a' }])).toEqual({ a: 1, b: 1 });
    expect(() => applyPatch({ a: 1 }, [{ op: 'test', path: '/a', value: 2 }])).toThrow();
    expect(applyPatch({ a: 1 }, [{ op: 'test', path: '/a', value: 1 }])).toEqual({ a: 1 });
  });

  it('handles escaped pointer tokens (~0 ~1)', () => {
    expect(parsePointer('/a~1b')).toEqual(['a/b']);
    expect(parsePointer('/m~0n')).toEqual(['m~n']);
    expect(applyPatch({ 'a/b': 1 }, [{ op: 'replace', path: '/a~1b', value: 2 }])).toEqual({ 'a/b': 2 });
  });

  it('supports the root replace extension (squash-to-full)', () => {
    expect(applyPatch({ a: 1 }, [{ op: 'replace', path: '', value: { z: 9 } }])).toEqual({ z: 9 });
  });
});

describe('A-E-20 delta-protocol — diff round-trip', () => {
  const cases: [unknown, unknown?][] = [
    [{ title: 'Old', count: 1 }, { title: 'New', count: 1 }],
    [{ a: { b: { c: 1 } } }, { a: { b: { c: 2 } } }],
    [{ items: [1, 2, 3] }, { items: [1, 3] }],
    [{ items: [1, 2] }, { items: [1, 3, 2] }],
    [{ items: [1, 2, 3, 4] }, { items: [0, 1, 2, 3, 4, 5] }],
    [{ items: [1, 2, 3] }, { items: [3, 2, 1] }],
    [{ nested: [{ id: 1, v: 'x' }, { id: 2, v: 'y' }] }, { nested: [{ id: 1, v: 'x' }, { id: 3, v: 'z' }] }],
    [{ kept: [1, 2, 3], gone: true }, { kept: [1, 2, 3, 4], added: 'yes' }],
    [[1, 2, 3], { obj: true }],
    [{ a: '1', b: 2 }, { a: '1', b: 'two' }],
    [{}],
  ];

  it('applyPatch(base, diff(base, target)) deep-equals target', () => {
    for (const [base, target = base] of cases) {
      const ops = diff(base, target);
      const applied = applyPatch(base, ops);
      expect(canonicalJson(applied)).toBe(canonicalJson(target));
    }
  });

  it('diff of identical documents is empty', () => {
    expect(diff({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] })).toEqual([]);
  });

  it('squash-to-full replaces a long op stream with one root replace', () => {
    const base = { a: 1, b: 2, c: 3 };
    const target = { a: 9, b: 8, c: 7, d: 4 };
    const ops = diff(base, target);
    const squashed = squashToFull(base, ops, { maxOps: 1 });
    expect(squashed.ops).toHaveLength(1);
    expect(squashed.ops[0]).toEqual({ op: 'replace', path: '', value: target });
    expect(applyPatch(base, squashed.ops)).toEqual(target);
  });

  it('keeps patches below the squash threshold as-is', () => {
    const base = { a: 1 };
    const squashed = squashToFull(base, [{ op: 'replace', path: '/a', value: 2 }], { maxOps: 3 });
    expect(squashed.ops).toHaveLength(1);
    expect(squashed.ops[0]!.path).toBe('/a');
  });
});

describe('A-E-21 wire-golden-tests — byte-exact patches', () => {
  it('golden: object property replace', () => {
    const ops = diff({ title: 'Old', count: 1 }, { title: 'New', count: 1 });
    expect(JSON.stringify(ops)).toBe('[{"op":"replace","path":"/title","value":"New"}]');
  });

  it('golden: array insertion at position 1', () => {
    const ops = diff({ items: [1, 2] }, { items: [1, 3, 2] });
    expect(JSON.stringify(ops)).toBe('[{"op":"add","path":"/items/1","value":3}]');
  });

  it('golden: array removal at position 1', () => {
    const ops = diff({ items: [1, 2, 3] }, { items: [1, 3] });
    expect(JSON.stringify(ops)).toBe('[{"op":"remove","path":"/items/1"}]');
  });

  it('golden: nested object recursion (sorted key order)', () => {
    const ops = diff({ a: { x: 1, y: 2 } }, { a: { x: 9, y: 2 } });
    expect(JSON.stringify(ops)).toBe('[{"op":"replace","path":"/a/x","value":9}]');
  });

  it('golden: root replace for type change', () => {
    const ops = diff([1, 2], { obj: true });
    expect(JSON.stringify(ops)).toBe('[{"op":"replace","path":"","value":{"obj":true}}]');
  });

  it('golden patches are byte-stable across repeated runs', () => {
    const base = { render: { nodes: [{ id: 1, tag: 'div' }, { id: 2, tag: 'text' }] } };
    const target = { render: { nodes: [{ id: 1, tag: 'div' }, { id: 3, tag: 'button' }] } };
    const first = JSON.stringify(diff(base, target));
    expect(JSON.stringify(diff(base, target))).toBe(first);
    expect(first.length).toBeGreaterThan(0);
  });
});

describe('A-E-19 schema-registry', () => {
  it('registers, resolves latest and validates payloads', () => {
    const registry = new SchemaRegistry();
    expect(registry.resolve('render_ui')!.version).toBe('1.0.0');
    expect(registry.validate('render_ui', { type: 'div', props: {}, children: [] }).ok).toBe(true);
    expect(registry.validate('render_ui', { props: {} }).ok).toBe(false);
    expect(registry.resolve('tool-schemas', '2.0.0')).toBeNull();
    registry.register({ kind: 'tool-schemas', version: '2.0.0', schema: { type: 'object' } });
    expect(registry.resolve('tool-schemas')!.version).toBe('2.0.0');
  });
});

describe('A-E-22 render-ui-toy', () => {
  const dsl = 'div(class="col"){ text(value="Hi") button(class="btn"){ text(value="Go") } }';

  it('parses and round-trips the compact DSL', () => {
    const tree = dslToTree(dsl);
    expect(tree.type).toBe('div');
    expect(tree.children).toHaveLength(2);
    expect(treeToDsl(tree)).toBe(dsl);
  });

  it('accepts OpenUI-style content arguments text("Hi")', () => {
    const tree = dslToTree('div{ text("Hi") }');
    expect(tree.children[0]!.props.value).toBe('Hi');
  });

  it('first turn ships full payload, follow-ups ship deltas', () => {
    const tree = dslToTree(dsl);
    const turn1 = renderDeltas(null, tree);
    expect(turn1.ops).toEqual([]);
    expect(turn1.base).toEqual(tree);
    const changed = dslToTree('div(class="col"){ text(value="Hi!") button(class="btn"){ text(value="Go") } }');
    const turn2 = renderDeltas(tree, changed);
    expect(turn2.ops.length).toBeGreaterThan(0);
    const rebuilt = applyPatch(tree, turn2.ops);
    expect(canonicalJson(rebuilt)).toBe(canonicalJson(changed));
  });

  it('the compact DSL costs less than JSON for the same tree', () => {
    const tree = dslToTree(dsl);
    const estimate = treeTokenEstimate(tree);
    expect(estimate.dslTokens).toBeLessThan(estimate.jsonTokens);
    expect(estimate.dslBytes).toBeLessThan(estimate.jsonBytes);
    expect(estimate.dslBytes / estimate.jsonBytes).toBeLessThan(0.7);
  });
});

describe('A-E-23 instruction-blocks', () => {
  const stableBlocks = [
    makeBlock('identity', 'identity', 'You are Substrate.'),
    makeBlock('task', 'task', 'Help the user with the current task.'),
    makeBlock('tools', 'tools', 'Available tools: a, b, c.'),
    makeBlock('schemas', 'schemas', '{"type":"object"}'),
    makeBlock('few-shot', 'few-shot', 'Example: x → y.'),
  ];
  const dynamicBlock = makeBlock('dynamic', 'dynamic', 'Current turn payload.', false);

  it('assembles the six regions in fixed order with stable prefix first', () => {
    const assembled = assemblePrompt([...stableBlocks, dynamicBlock]);
    expect(assembled.prompt.startsWith('<!-- identity -->')).toBe(true);
    expect(assembled.prompt.endsWith('Current turn payload.\n')).toBe(true);
    expect(assembled.stableTokens).toBeGreaterThan(0);
    expect(assembled.dynamicTokens).toBeGreaterThan(0);
  });

  it('identical stable blocks produce an identical byte prefix across turns', () => {
    const turn1 = assemblePrompt([...stableBlocks, dynamicBlock]);
    const turn2 = assemblePrompt([
      ...stableBlocks,
      makeBlock('dynamic', 'dynamic', 'A completely different payload.', false),
    ]);
    const marker = '<!-- dynamic -->\n';
    const shared = stablePrefixBytes(turn1.prompt, turn2.prompt);
    expect(shared).toBe(turn1.stablePart.length + marker.length);
    expect(shared).toBe(cacheEligiblePrefix(stableBlocks).length + marker.length);
    expect(shared).toBeGreaterThan(turn1.dynamicPart.length);
  });

  it('a change inside a stable block breaks the prefix there', () => {
    const turn1 = assemblePrompt([...stableBlocks, dynamicBlock]);
    const changed = assemblePrompt([
      ...stableBlocks.slice(0, 2),
      makeBlock('tools', 'tools', 'Available tools: a, b.'),
      ...stableBlocks.slice(3),
      dynamicBlock,
    ]);
    const shared = stablePrefixBytes(turn1.prompt, changed.prompt);
    expect(shared).toBeLessThan(cacheEligiblePrefix(stableBlocks).length);
    expect(shared).toBeGreaterThanOrEqual(0);
  });
});
