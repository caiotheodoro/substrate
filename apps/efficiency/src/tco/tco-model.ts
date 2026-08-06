import type { StepRecord } from '@substrate/substrate';
import type { PriceCatalog, PriceRow } from './price-catalog.js';

/**
 * A-E-27 tco-model — workload → cost curves across the lever grid, honest
 * about non-token costs. Token cost is only one line: latency (human and
 * machinery time), ops (per-step overhead) and hardware (amortized serving
 * cost) are counted as their own lines, so "token cost is not total cost"
 * is a first-class property, not a footnote.
 */

export interface TcoConfig {
  /** $ per ms of latency (waiting cost; 0.00002 ≈ $1.20/min of labor). */
  latencyCostPerMsUsd: number;
  /** fixed per-step platform overhead. */
  opsCostPerStepUsd: number;
  /** amortized hardware cost per step (GPU/VRAM rental share). */
  hardwareCostPerStepUsd: number;
}

export const DEFAULT_TCO_CONFIG: TcoConfig = {
  latencyCostPerMsUsd: 0.00002,
  opsCostPerStepUsd: 0.0001,
  hardwareCostPerStepUsd: 0.0005,
};

export interface StepCost {
  tokenCost: number;
  latencyCost: number;
  opsCost: number;
  hardwareCost: number;
  total: number;
}

export function stepCost(step: StepRecord, row: PriceRow, config: TcoConfig): StepCost {
  const perM = 1e6;
  const tokenCost =
    (step.inputTokens * row.inputPerMtok) / perM +
    (step.cachedInputTokens * row.cachedInputPerMtok) / perM +
    (step.outputTokens * row.outputPerMtok) / perM +
    (step.cacheEvent === 'write' ? (step.inputTokens * row.cacheWritePerMtok) / perM : 0);
  const latencyCost = step.latencyMs * config.latencyCostPerMsUsd;
  const opsCost = config.opsCostPerStepUsd;
  const hardwareCost = config.hardwareCostPerStepUsd;
  return {
    tokenCost,
    latencyCost,
    opsCost,
    hardwareCost,
    total: tokenCost + latencyCost + opsCost + hardwareCost,
  };
}

export interface WorkloadCost extends StepCost {
  steps: number;
  totalInputTokens: number;
  totalCachedInputTokens: number;
  totalOutputTokens: number;
}

export function workloadCost(
  steps: readonly StepRecord[],
  row: PriceRow,
  config: TcoConfig = DEFAULT_TCO_CONFIG,
): WorkloadCost {
  let tokenCost = 0;
  let latencyCost = 0;
  let opsCost = 0;
  let hardwareCost = 0;
  let totalInput = 0;
  let totalCached = 0;
  let totalOutput = 0;
  for (const step of steps) {
    const c = stepCost(step, row, config);
    tokenCost += c.tokenCost;
    latencyCost += c.latencyCost;
    opsCost += c.opsCost;
    hardwareCost += c.hardwareCost;
    totalInput += step.inputTokens;
    totalCached += step.cachedInputTokens;
    totalOutput += step.outputTokens;
  }
  return {
    tokenCost,
    latencyCost,
    opsCost,
    hardwareCost,
    total: tokenCost + latencyCost + opsCost + hardwareCost,
    steps: steps.length,
    totalInputTokens: totalInput,
    totalCachedInputTokens: totalCached,
    totalOutputTokens: totalOutput,
  };
}

/** A knob set on the lever grid: provider × model × quant × cache policy. */
export interface LeverOption {
  provider: string;
  model: string;
  quantization: string | null;
  cache: boolean;
}

export interface LeverCost {
  option: LeverOption;
  cost: WorkloadCost;
}

export function leverGridCost(
  steps: readonly StepRecord[],
  options: readonly LeverOption[],
  catalog: PriceCatalog,
  config: TcoConfig = DEFAULT_TCO_CONFIG,
): LeverCost[] {
  return options.map((option) => ({
    option,
    cost: workloadCost(steps, priceRowOf(catalog, option), config),
  }));
}

export function priceRowOf(catalog: PriceCatalog, option: LeverOption): PriceRow {
  const row = catalog.providers[option.provider]?.models[option.model];
  if (row === undefined) throw new Error(`no price for ${option.provider}/${option.model}`);
  return row;
}

export function bestLever(
  grid: readonly LeverCost[],
): LeverCost | null {
  if (grid.length === 0) return null;
  return [...grid].sort((a, b) => a.cost.total - b.cost.total)[0]!;
}

export function validateBill(predictedUsd: number, actualUsd: number): {
  marginPct: number;
  within: boolean;
  predictedUsd: number;
  actualUsd: number;
} {
  const marginPct = actualUsd === 0 ? 0 : Math.abs(predictedUsd - actualUsd) / actualUsd * 100;
  return { marginPct, within: marginPct <= 15, predictedUsd, actualUsd };
}
