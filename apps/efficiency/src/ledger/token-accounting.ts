/**
 * A-E-04 token-accounting — EXCLUSIVE-bucket normalization.
 *
 * The C4 contract is exclusive (Langfuse convention): `inputTokens` never
 * includes `cachedInputTokens`. Providers are inclusive or ambiguous
 * (OpenAI reports prompt_tokens including cached; Ollama reports
 * prompt_eval_count with no cache split). Every conversion must produce
 * exclusive buckets, and every record crossing the ledger boundary is
 * asserted exclusive. Token counting uses a tiktoken-style byte/char
 * fallback (≈4 chars/token BPE heuristic) with an interface for real
 * tokenizers (tiktoken / @anthropic-ai/tokenizer / HF) behind it — the
 * real ones are a runtime dependency, so they load lazily, never at import.
 */

/** Interface real tokenizers implement when they are installed (lazy). */
export interface Tokenizer {
  countTokens(text: string): number;
}

/** tiktoken-style byte fallback: BPE roughly compresses ~4 bytes/token. */
export class ByteFallbackTokenizer implements Tokenizer {
  constructor(private readonly bytesPerToken = 4) {}

  countTokens(text: string): number {
    return Math.max(1, Math.ceil(Buffer.byteLength(text, 'utf8') / this.bytesPerToken));
  }
}

/** Character fallback for non-UTF8-agnostic estimates. */
export class CharFallbackTokenizer implements Tokenizer {
  constructor(private readonly charsPerToken = 4) {}

  countTokens(text: string): number {
    return Math.max(1, Math.ceil([...text].length / this.charsPerToken));
  }
}

export const defaultTokenizer = new ByteFallbackTokenizer();

/**
 * Normalize a provider-inclusive input count to exclusive buckets.
 * `inputInclusive` = what the provider billed (cached tokens included).
 * Throws if the provider reported more cached tokens than total input —
 * that is a corrupt usage record, not a small negative bucket.
 */
export function normalizeInclusiveToExclusive(
  inputInclusive: number,
  cachedTokens: number,
): { inputTokens: number; cachedInputTokens: number } {
  if (cachedTokens < 0 || inputInclusive < 0) throw new Error('negative token count');
  if (cachedTokens > inputInclusive) {
    throw new Error(
      `cached tokens (${cachedTokens}) exceed inclusive input (${inputInclusive})`,
    );
  }
  return { inputTokens: inputInclusive - cachedTokens, cachedInputTokens: cachedTokens };
}

/** The ledger invariant: exclusive buckets are non-negative ints. */
export function assertExclusiveBuckets(record: {
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
}): void {
  for (const v of [record.inputTokens, record.cachedInputTokens, record.outputTokens]) {
    if (!Number.isInteger(v) || v < 0) throw new Error(`non-integer or negative bucket: ${v}`);
  }
}

/** Enforce exclusive buckets against a known provider total, when the provider gave one. */
export function enforceExclusiveAgainstProvider(
  record: { inputTokens: number; cachedInputTokens: number },
  providerInputTotal: number,
): void {
  assertExclusiveBuckets({ ...record, outputTokens: 0 });
  if (record.inputTokens + record.cachedInputTokens !== providerInputTotal) {
    throw new Error(
      `exclusive sum ${record.inputTokens + record.cachedInputTokens} != provider total ${providerInputTotal}`,
    );
  }
}

/** Split a prompt into stable (cache-eligible) and dynamic token buckets. */
export function estimatePromptTokens(
  stableText: string,
  dynamicText: string,
  tokenizer: Tokenizer = defaultTokenizer,
): { inputTokens: number; cachedInputTokens: number; total: number } {
  const stable = tokenizer.countTokens(stableText);
  const dynamic = tokenizer.countTokens(dynamicText);
  return { inputTokens: dynamic, cachedInputTokens: stable, total: stable + dynamic };
}

/**
 * Load a real tokenizer if one is installed (tiktoken, @anthropic-ai/tokenizer,
 * @xenova/transformers...). Never a runtime dependency: absence falls back to
 * the byte heuristic with the same interface.
 */
export async function loadRealTokenizerLazy(): Promise<Tokenizer | null> {
  const specifier: string = 'tiktoken';
  try {
    const mod = (await import(specifier)) as {
      get_encoding?: (name: string) => { encode(text: string, allowed: string[] | 'all'): number[] };
    };
    const enc = mod.get_encoding?.('cl100k_base');
    if (enc === undefined) return null;
    return { countTokens: (text: string) => enc.encode(text, 'all').length };
  } catch {
    return null;
  }
}
