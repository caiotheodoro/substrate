import { describe, expect, it } from 'vitest';
import { KNOWN_SHOCKS, SHOCK_INTERVENTIONS, getShock } from './index';

describe('scenario library', () => {
  it('has the four historical shocks with no TBD seeds', () => {
    expect(KNOWN_SHOCKS.map((s) => s.id)).toEqual([
      'covid-2020',
      'supplychain-2021',
      'inflation-2022',
      'tariffs-2025',
    ]);
    for (const s of KNOWN_SHOCKS) {
      expect(s.seed).not.toContain('TBD');
      expect(s.realizedOutcome).not.toContain('TBD');
      expect(s.version).toBeTruthy();
      expect(s.series.length).toBeGreaterThan(0);
    }
  });

  it('marks the 2025 tariff wave as the holdout', () => {
    expect(getShock('tariffs-2025').realizedOutcome).toContain('HOLDOUT');
  });

  it('has replayable interventions for 01 stress-testing', () => {
    expect(SHOCK_INTERVENTIONS.map((i) => i.id)).toHaveLength(4);
    for (const i of SHOCK_INTERVENTIONS) {
      expect(i.channels.length).toBeGreaterThan(0);
      expect(i.profile).toBeTruthy();
    }
  });

  it('rejects unknown shocks', () => {
    expect(() => getShock('nope')).toThrow();
  });
});
