import type { DecisionRecord } from '@substrate/substrate';
import type { Stores, ThresholdBand } from '../types';
import { DEFAULT_GATE_OPTIONS, GateOptions, paretoFrontier, SweepPoint, thresholdSweep } from './gate-core';

export const DEFAULT_THRESHOLD: Omit<ThresholdBand, 'taskType'> = {
  executeThreshold: DEFAULT_GATE_OPTIONS.executeThreshold,
  rejectThreshold: DEFAULT_GATE_OPTIONS.rejectThreshold,
};

export class ThresholdManager {
  constructor(private stores: Stores) {}

  async get(taskType: string): Promise<ThresholdBand> {
    const found = await this.stores.thresholds.get(taskType);
    return found ?? { taskType, ...DEFAULT_THRESHOLD };
  }

  async set(taskType: string, band: Omit<ThresholdBand, 'taskType'>): Promise<ThresholdBand> {
    if (band.rejectThreshold >= band.executeThreshold) {
      throw new Error('rejectThreshold must be below executeThreshold');
    }
    const full: ThresholdBand = { taskType, ...band };
    await this.stores.thresholds.set(taskType, band);
    return full;
  }

  async list(): Promise<ThresholdBand[]> {
    const all = await this.stores.thresholds.list();
    return all.length > 0 ? all : [{ taskType: 'default', ...DEFAULT_THRESHOLD }];
  }

  async estimate(taskType: string, records: DecisionRecord[]): Promise<{
    current: ThresholdBand;
    frontier: SweepPoint[];
    recommended: SweepPoint;
  }> {
    const samples = records.map((r) => ({ score: heuristicFromFeatures(r.confidenceFeatures), outcome: r.outcome ?? true }));
    const points = thresholdSweep(samples);
    const frontier = paretoFrontier(points);
    const recommended = frontier.length > 0 ? frontier[Math.floor(frontier.length / 2)]! : points[0]!;
    return { current: await this.get(taskType), frontier, recommended };
  }
}

export function heuristicFromFeatures(features: Record<string, unknown>): number {
  const candidate = features['score'];
  return typeof candidate === 'number' && Number.isFinite(candidate) ? candidate : 0.5;
}

export interface ParetoEstimatorResult {
  current: ThresholdBand;
  frontier: SweepPoint[];
  recommended: SweepPoint;
}

export async function estimatePareto(stores: Stores, taskType: string): Promise<ParetoEstimatorResult> {
  const mgr = new ThresholdManager(stores);
  const records = await stores.decisions.list();
  return mgr.estimate(taskType, records);
}
