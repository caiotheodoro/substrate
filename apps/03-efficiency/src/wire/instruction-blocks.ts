
import { InstructionBlockSchema, type InstructionBlock } from '@substrate/substrate';
import type { PromptRegion } from '../lib/prompt-regions.js';
import { defaultTokenizer, type Tokenizer } from '../ledger/token-accounting.js';

/**
 * A-E-23 instruction-blocks — 6-layer cache-stable prompt assembly.
 *
 * A prompt is assembled from the six C7 regions in a fixed order. The
 * first five (identity, task, tools, schemas, few-shot) are STABLE — they
 * do not change across turns and therefore form the cache-eligible prefix;
 * the last (dynamic) region is the only thing that moves. `stablePrefix`
 * gives the byte boundary of the cache-eligible head: two prompts that
 * share the same stable blocks share an identical byte prefix, which is
 * exactly what a prefix cache needs.
 */

export const REGION_ORDER: readonly PromptRegion[] = [
  'identity',
  'task',
  'tools',
  'schemas',
  'few-shot',
  'dynamic',
];

export interface AssembledPrompt {
  prompt: string;
  stablePart: string;
  dynamicPart: string;
  stableTokens: number;
  dynamicTokens: number;
}

export function assemblePrompt(
  blocks: readonly InstructionBlock[],
  tokenizer: Tokenizer = defaultTokenizer,
): AssembledPrompt {
  const stable: string[] = [];
  const dynamic: string[] = [];
  for (const region of REGION_ORDER) {
    const block = blocks.find((b) => b.region === region);
    if (block === undefined) continue;
    InstructionBlockSchema.parse(block);
    const text = `<!-- ${block.id} -->\n${block.content}\n`;
    if (block.stable) stable.push(text);
    else dynamic.push(text);
  }
  const stablePart = stable.join('');
  const dynamicPart = dynamic.join('');
  return {
    prompt: stablePart + dynamicPart,
    stablePart,
    dynamicPart,
    stableTokens: tokenizer.countTokens(stablePart),
    dynamicTokens: tokenizer.countTokens(dynamicPart),
  };
}

/** Byte length of the longest identical prefix of two prompts. */
export function stablePrefixBytes(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let i = 0;
  while (i < max && a.charCodeAt(i) === b.charCodeAt(i)) i++;
  return i;
}

export function cacheEligiblePrefix(blocks: readonly InstructionBlock[]): string {
  const stable = blocks
    .filter((b) => b.stable)
    .sort((x, y) => REGION_ORDER.indexOf(x.region) - REGION_ORDER.indexOf(y.region))
    .map((b) => `<!-- ${b.id} -->\n${b.content}\n`);
  return stable.join('');
}

export function makeBlock(
  id: string,
  region: PromptRegion,
  content: string,
  stable = true,
): InstructionBlock {
  return InstructionBlockSchema.parse({ id, region, content, stable });
}
