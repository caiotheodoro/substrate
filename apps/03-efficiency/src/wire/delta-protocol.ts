import type { PatchOp } from '@substrate/substrate';
import { canonicalJson } from '@substrate/substrate';
import { defaultTokenizer, type Tokenizer } from '../ledger/token-accounting.js';

/**
 * A-E-20 delta-protocol — RFC 6902 JSON-Patch, implemented here (no
 * dependency) because the wire protocol is a research artifact: diff,
 * apply and squash must be byte-exact, deterministic and inspectable.
 *
 * Coverage: add / remove / replace / move / copy / test, object keys and
 * array indices, "-" append, root replace ("full-squash" extension used by
 * the delta bench). `diff` produces removes-then-adds via LCS alignment,
 * which makes golden patches byte-stable across runs.
 */

export type { PatchOp };

export function escapeToken(token: string): string {
  return token.replace(/~/g, '~0').replace(/\//g, '~1');
}

export function unescapeToken(token: string): string {
  return token.replace(/~1/g, '/').replace(/~0/g, '~');
}

export function parsePointer(path: string): string[] {
  if (path === '') return [];
  return path.split('/').slice(1).map(unescapeToken);
}

export function joinPointer(base: string, token: string): string {
  return `${base}/${escapeToken(token)}`;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function deepEq(a: unknown, b: unknown): boolean {
  return canonicalJson(a) === canonicalJson(b);
}

function parseArrayIndex(token: string, length: number, allowAppend: boolean): number {
  if (token === '-') {
    if (!allowAppend) throw new Error(`'-' not allowed here`);
    return length;
  }
  const idx = Number(token);
  if (!Number.isInteger(idx) || idx < 0) throw new Error(`bad array index: ${token}`);
  if (allowAppend ? idx > length : idx >= length) {
    throw new Error(`array index out of range: ${token} (length ${length})`);
  }
  return idx;
}

function resolveParent(doc: unknown, tokens: string[]): unknown {
  let cur: unknown = doc;
  for (const token of tokens) {
    if (Array.isArray(cur)) {
      cur = cur[parseArrayIndex(token, cur.length, true)];
    } else if (isPlainObject(cur)) {
      if (!(token in cur)) throw new Error(`path missing: ${token}`);
      cur = cur[token];
    } else {
      throw new Error(`cannot descend into non-container at ${token}`);
    }
    if (cur === undefined) throw new Error(`path missing at ${token}`);
  }
  return cur;
}

function resolveValue(doc: unknown, tokens: string[]): unknown {
  if (tokens.length === 0) return doc;
  const parent = resolveParent(doc, tokens.slice(0, -1));
  return valueAt(parent, tokens[tokens.length - 1]!);
}

function valueAt(parent: unknown, last: string): unknown {
  if (Array.isArray(parent)) return parent[parseArrayIndex(last, parent.length, false)];
  if (isPlainObject(parent)) {
    if (!(last in parent)) throw new Error(`path missing: /${last}`);
    return parent[last];
  }
  throw new Error('cannot index non-container');
}

function insertAt(parent: unknown, last: string, value: unknown, allowAppend: boolean): void {
  if (Array.isArray(parent)) {
    const idx = parseArrayIndex(last, parent.length, allowAppend);
    parent.splice(idx, 0, value);
  } else if (isPlainObject(parent)) {
    parent[last] = value;
  } else {
    throw new Error('cannot insert into non-container');
  }
}

function applyAt(doc: unknown, tokens: string[], op: PatchOp): void {
  if (tokens.length === 0) {
    throw new Error(`root ${op.op} must be handled by applyPatch`);
  }
  const parentTokens = tokens.slice(0, -1);
  const last = tokens[tokens.length - 1]!;
  const parent = resolveParent(doc, parentTokens);
  switch (op.op) {
    case 'add':
      insertAt(parent, last, structuredClone(op.value), true);
      break;
    case 'remove': {
      if (Array.isArray(parent)) {
        parent.splice(parseArrayIndex(last, parent.length, false), 1);
      } else if (isPlainObject(parent)) {
        if (!(last in parent)) throw new Error(`remove: missing ${op.path}`);
        delete parent[last];
      } else throw new Error('cannot remove from non-container');
      break;
    }
    case 'replace': {
      if (Array.isArray(parent)) {
        parent[parseArrayIndex(last, parent.length, false)] = structuredClone(op.value);
      } else if (isPlainObject(parent)) {
        if (!(last in parent)) throw new Error(`replace: missing ${op.path}`);
        parent[last] = structuredClone(op.value);
      } else throw new Error('cannot replace in non-container');
      break;
    }
    case 'move': {
      const from = parsePointer(op.from);
      const taken = takeValue(doc, from);
      insertAt(parent, last, taken, true);
      break;
    }
    case 'copy': {
      const from = parsePointer(op.from);
      insertAt(parent, last, structuredClone(resolveValue(doc, from)), true);
      break;
    }
    case 'test': {
      const actual = resolveValue(doc, tokens);
      if (!deepEq(actual, op.value)) throw new Error(`test failed at ${op.path}`);
      break;
    }
  }
}

function takeValue(doc: unknown, tokens: string[]): unknown {
  if (tokens.length === 0) throw new Error('move/copy from root not supported');
  const parent = resolveParent(doc, tokens.slice(0, -1));
  const last = tokens[tokens.length - 1]!;
  if (Array.isArray(parent)) {
    const idx = parseArrayIndex(last, parent.length, false);
    const [taken] = parent.splice(idx, 1);
    return taken;
  }
  if (isPlainObject(parent)) {
    if (!(last in parent)) throw new Error(`move: missing ${tokens.join('/')}`);
    const taken = parent[last];
    delete parent[last];
    return taken;
  }
  throw new Error('cannot move from non-container');
}

/** Apply an RFC 6902 patch to a document (structured-clone semantics). */
export function applyPatch<T>(doc: T, ops: readonly PatchOp[]): T {
  let work: unknown = structuredClone(doc);
  for (const op of ops) {
    const tokens = parsePointer(op.path);
    if (tokens.length === 0) {
      if (op.op === 'replace' || op.op === 'add') {
        work = structuredClone(op.value);
      } else if (op.op === 'test') {
        if (!deepEq(work, op.value)) throw new Error('test failed at root');
      } else {
        throw new Error(`root ${op.op} not allowed`);
      }
    } else {
      applyAt(work, tokens, op);
    }
  }
  return work as T;
}

/**
 * RFC 6902 diff: objects by sorted-key recursion, arrays by LCS alignment.
 * `applyPatch(base, diff(base, target))` is guaranteed deep-equal to
 * `target` for any JSON value. Deterministic: same inputs → same ops.
 */
export function diff(base: unknown, target: unknown): PatchOp[] {
  if (deepEq(base, target)) return [];
  if (isPlainObject(base) && isPlainObject(target)) return diffObjects(base, target, '');
  if (Array.isArray(base) && Array.isArray(target)) return diffArrays(base, target, '');
  return [{ op: 'replace', path: '', value: target }];
}

function diffValues(base: unknown, target: unknown, path: string): PatchOp[] {
  if (deepEq(base, target)) return [];
  if (isPlainObject(base) && isPlainObject(target)) return diffObjects(base, target, path);
  if (Array.isArray(base) && Array.isArray(target)) return diffArrays(base, target, path);
  return [{ op: 'replace', path, value: target }];
}

function diffObjects(
  base: Record<string, unknown>,
  target: Record<string, unknown>,
  path: string,
): PatchOp[] {
  const ops: PatchOp[] = [];
  const keys = [...new Set([...Object.keys(base), ...Object.keys(target)])].sort();
  for (const key of keys) {
    const childPath = joinPointer(path, key);
    const inBase = key in base;
    const inTarget = key in target;
    if (!inTarget) {
      ops.push({ op: 'remove', path: childPath });
    } else if (!inBase) {
      ops.push({ op: 'add', path: childPath, value: target[key] });
    } else {
      ops.push(...diffValues(base[key], target[key], childPath));
    }
  }
  return ops;
}

/**
 * Array alignment predicate: scalars match only when deep-equal; containers
 * align positionally when they are plausibly the same element — both plain
 * objects with the same `type` key (UI nodes), or both arrays — so a changed
 * subtree produces field-level ops instead of remove+add of the whole
 * element. Objects without a `type` key align only when deep-equal.
 */
function elementMatch(a: unknown, b: unknown): boolean {
  if (deepEq(a, b)) return true;
  const aObj = isPlainObject(a);
  const bObj = isPlainObject(b);
  if (aObj && bObj) {
    if ('type' in a && 'type' in b) {
      return (a as Record<string, unknown>)['type'] === (b as Record<string, unknown>)['type'];
    }
    return false;
  }
  return Array.isArray(a) && Array.isArray(b);
}

function diffArrays(base: unknown[], target: unknown[], path: string): PatchOp[] {
  const n = base.length;
  const m = target.length;

  const match = Array.from({ length: n }, () => new Array<boolean>(m).fill(false));
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < m; j++) {
      match[i]![j] = elementMatch(base[i], target[j]);
    }
  }

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i]![j] = match[i]![j]
        ? dp[i + 1]![j + 1]! + 1
        : Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!);
    }
  }

  const keepA = new Set<number>();
  const keepB = new Set<number>();
  const aligned: Array<[number, number]> = [];
  {
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (match[i]![j]) {
        keepA.add(i);
        keepB.add(j);
        aligned.push([i, j]);
        i++;
        j++;
      } else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) {
        i++;
      } else {
        j++;
      }
    }
  }

  const ops: PatchOp[] = [];
  for (let i = n - 1; i >= 0; i--) {
    if (!keepA.has(i)) ops.push({ op: 'remove', path: `${path}/${i}` });
  }
  for (let j = 0; j < m; j++) {
    if (!keepB.has(j)) ops.push({ op: 'add', path: `${path}/${j}`, value: target[j] });
  }
  for (const [i, j] of aligned) {
    if (!deepEq(base[i], target[j])) {
      ops.push(...diffValues(base[i], target[j], `${path}/${j}`));
    }
  }
  return ops;
}

/**
 * Squash-to-full heuristic: once a patch exceeds `maxOps`, replace the
 * whole op stream with a single root `replace` of the fully-applied state.
 * The crossover where this becomes cheaper than continuing patches is the
 * subject of the delta-100th-turn benchmark (A-E-32).
 */
export function squashToFull<T>(
  base: T,
  ops: readonly PatchOp[],
  opts: { maxOps?: number } = {},
): { ops: PatchOp[]; applied: T } {
  const applied = applyPatch(base, ops);
  const maxOps = opts.maxOps ?? 1;
  if (ops.length > maxOps) {
    return { ops: [{ op: 'replace', path: '', value: applied }], applied };
  }
  return { ops: [...ops], applied };
}

export function opsTokenEstimate(ops: readonly PatchOp[], tokenizer: Tokenizer = defaultTokenizer): number {
  return tokenizer.countTokens(canonicalJson(ops));
}

export function opsBytes(ops: readonly PatchOp[]): number {
  return Buffer.byteLength(canonicalJson(ops), 'utf8');
}
