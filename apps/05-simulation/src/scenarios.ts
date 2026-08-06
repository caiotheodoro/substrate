import { KNOWN_SHOCKS } from '@substrate/scenarios';

/**
 * Read-only scenario table for sim-api :8300 `/scenarios`.
 * Derived from the FROZEN @substrate/scenarios package — never edited here.
 * `tariffs-2025` is the end-to-end HOLDOUT (BUILD.md integrity rule 2).
 */
export interface ScenarioDoc {
  id: string;
  name: string;
  window: string;
  series: string[];
  holdout: boolean;
  seed: string;
  realizedOutcome: string;
}

const HOLDOUT = new Set(['tariffs-2025']);

export function scenarioTable(): ScenarioDoc[] {
  return KNOWN_SHOCKS.map((s) => ({
    id: s.id,
    name: s.name,
    window: s.window,
    series: [...s.series],
    holdout: HOLDOUT.has(s.id),
    seed: s.seed,
    realizedOutcome: s.realizedOutcome,
  }));
}

export function getScenario(id: string): ScenarioDoc | undefined {
  return scenarioTable().find((s) => s.id === id);
}