import { readFileSync } from 'node:fs';
import { dataFile } from '../lib/paths.js';

/**
 * A-E-28 price-catalog — JSON snapshots of per-million-token prices.
 * Tests always inject their own catalog; the shipped snapshot is plausible
 * local prices (ollama $0, hosted equivalents via litellm). Cache rows are
 * explicit: input / cached-input / output / cache-write.
 */

export interface PriceRow {
  inputPerMtok: number;
  cachedInputPerMtok: number;
  outputPerMtok: number;
  cacheWritePerMtok: number;
}

export interface PriceCatalog {
  catalogVersion: string;
  providers: Record<string, { models: Record<string, PriceRow> }>;
}

export const DEFAULT_PRICE_CATALOG_PATH = dataFile('price-catalog.json');

export function loadPriceCatalog(path = DEFAULT_PRICE_CATALOG_PATH): PriceCatalog {
  return JSON.parse(readFileSync(path, 'utf8')) as PriceCatalog;
}

export function priceRow(catalog: PriceCatalog, provider: string, model: string): PriceRow {
  const row = catalog.providers[provider]?.models[model];
  if (row === undefined) throw new Error(`no price row for ${provider}/${model}`);
  return row;
}
