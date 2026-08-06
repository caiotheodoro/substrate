import { diff, applyPatch, type PatchOp } from './delta-protocol.js';
import { defaultTokenizer, type Tokenizer } from '../ledger/token-accounting.js';

/**
 * A-E-22 render-ui-toy — OpenUI-style compact streaming DSL + delta edits.
 *
 * A tiny grammar for generated UI (the same idea as OpenUI's DSL): the
 * wire carries a compact string instead of JSON, and follow-up turns carry
 * RFC 6902 deltas instead of a full re-render.
 *
 *   div(class="col"){ text("Hi") button(class="btn"){ "Go" } }
 *
 * `dslToTree`/`treeToDsl` round-trip; `treeToJson` is the canonical JSON
 * form the wire registry validates; `renderDeltas` produces the delta
 * payload for follow-up turns (full tree on turn 1, ops afterwards).
 */

export interface UiNode {
  type: string;
  props: Record<string, string>;
  children: UiNode[];
}

function tokenize(src: string): string[] {
  const tokens: string[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i]!;
    if (/[\s,]/.test(ch)) {
      i++;
      continue;
    }
    if (/[(){}]/.test(ch)) {
      tokens.push(ch);
      i++;
      continue;
    }
    if (ch === '=') {
      tokens.push(ch);
      i++;
      continue;
    }
    if (ch === '"') {
      let j = i + 1;
      let out = '';
      while (j < src.length && src[j] !== '"') {
        if (src[j] === '\\' && j + 1 < src.length) {
          out += src[j + 1];
          j += 2;
        } else {
          out += src[j]!;
          j++;
        }
      }
      if (j >= src.length) throw new Error(`unterminated string in DSL`);
      tokens.push(JSON.stringify(out));
      i = j + 1;
      continue;
    }
    let j = i;
    while (j < src.length && !/[\s,=(){}"]/.test(src[j]!)) j++;
    tokens.push(src.slice(i, j));
    i = j;
  }
  return tokens;
}

export function dslToTree(src: string): UiNode {
  const tokens = tokenize(src);
  let pos = 0;

  const parseString = (): string => {
    const tok = tokens[pos];
    if (tok === undefined) throw new Error(`unexpected end of DSL`);
    if (tok.startsWith('"')) {
      pos++;
      return JSON.parse(tok) as string;
    }
    throw new Error(`expected string, got ${tok}`);
  };

  const parseNode = (): UiNode | string => {
    const tok = tokens[pos];
    if (tok === undefined) throw new Error(`unexpected end of DSL`);
    if (tok.startsWith('"')) return parseString();
    if (!/^[a-z_][a-z0-9_]*$/.test(tok)) throw new Error(`bad tag: ${tok}`);
    pos++;
    const props: Record<string, string> = {};
    if (tokens[pos] === '(') {
      pos++;
      while (tokens[pos] !== ')' && tokens[pos] !== undefined) {
        const key = tokens[pos];
        if (key === undefined) throw new Error('unterminated attrs');
        if (key.startsWith('"')) {
          // OpenUI-style content argument: text("Hi") → props.value
          props['value'] = parseString();
          if (tokens[pos] === ',') pos++;
          continue;
        }
        if (!/^[a-z_][a-z0-9_-]*$/.test(key)) throw new Error(`bad attr: ${key}`);
        pos++;
        if (tokens[pos] !== '=') throw new Error(`expected = after ${key}`);
        pos++;
        props[key] = parseString();
        if (tokens[pos] === ',') pos++;
      }
      if (tokens[pos] !== ')') throw new Error(`unterminated attrs for ${tok}`);
      pos++;
    }
    if (tokens[pos] !== '{') {
      return { type: tok, props, children: [] };
    }
    pos++;
    const children: UiNode[] = [];
    while (tokens[pos] !== '}' && tokens[pos] !== undefined) {
      const child = parseNode();
      if (typeof child === 'string') {
        children.push({ type: 'text', props: { value: child }, children: [] });
      } else {
        children.push(child);
      }
    }
    if (tokens[pos] !== '}') throw new Error(`unterminated node ${tok}`);
    pos++;
    return { type: tok, props, children };
  };

  const root = parseNode();
  if (typeof root === 'string') throw new Error('root must be a node');
  if (pos !== tokens.length) throw new Error(`trailing tokens in DSL`);
  return root;
}

export function treeToDsl(node: UiNode): string {
  const attrs = Object.entries(node.props)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(',');
  const open = `${node.type}${attrs === '' ? '' : `(${attrs})`}`;
  if (node.children.length === 0) return open;
  const inner = node.children.map((c) => treeToDsl(c)).join(' ');
  return `${open}{ ${inner} }`;
}

export function treeToJson(node: UiNode): unknown {
  return node;
}

export function treeTokenEstimate(
  node: UiNode,
  tokenizer: Tokenizer = defaultTokenizer,
): { dslTokens: number; jsonTokens: number; dslBytes: number; jsonBytes: number } {
  const dsl = treeToDsl(node);
  const json = JSON.stringify(node);
  return {
    dslTokens: tokenizer.countTokens(dsl),
    jsonTokens: tokenizer.countTokens(json),
    dslBytes: Buffer.byteLength(dsl, 'utf8'),
    jsonBytes: Buffer.byteLength(json, 'utf8'),
  };
}

export interface RenderDelta {
  base: UiNode | null;
  ops: PatchOp[];
  tokens: number;
}

/** Turn 1: full payload. Follow-ups: RFC 6902 ops vs the previous tree. */
export function renderDeltas(
  previous: UiNode | null,
  next: UiNode,
  tokenizer: Tokenizer = defaultTokenizer,
): RenderDelta {
  if (previous === null) {
    return { base: next, ops: [], tokens: treeTokenEstimate(next, tokenizer).jsonTokens };
  }
  const ops = diff(previous, next);
  return { base: previous, ops, tokens: tokenizer.countTokens(JSON.stringify(ops)) };
}

/** A streaming sequence of full-payload snapshots, one node append at a time. */
export function streamFrames(node: UiNode): UiNode[] {
  const frames: UiNode[] = [];
  const walk = (n: UiNode): void => {
    frames.push(n);
    for (const child of n.children) walk(child);
  };
  walk(node);
  return frames;
}

export function parseDsl(src: string): UiNode {
  return dslToTree(src);
}

export function applyDslDelta(previous: UiNode, ops: PatchOp[]): UiNode {
  return applyPatch(previous, ops);
}
