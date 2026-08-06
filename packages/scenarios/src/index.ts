export interface ShockScenario {
  id: string;
  name: string;
  /** The realized outcome the scenario scored against. */
  realizedOutcome: string;
  /** Window of the historical shock. */
  window: string;
  /** Unified seed material describing the pre-shock world. */
  seed: string;
}

export const KNOWN_SHOCKS: ShockScenario[] = [
  {
    id: 'covid-2020',
    name: '2020 Pandemic Demand Shift',
    realizedOutcome: 'TBD',
    window: '2020-03/2020-06',
    seed: 'TBD',
  },
  {
    id: 'supplychain-2021',
    name: '2021 Supply Chain Crisis',
    realizedOutcome: 'TBD',
    window: '2021',
    seed: 'TBD',
  },
  {
    id: 'inflation-2022',
    name: '2022 Inflation Spike',
    realizedOutcome: 'TBD',
    window: '2022',
    seed: 'TBD',
  },
  {
    id: 'tariffs-2025',
    name: '2025 Tariff Waves',
    realizedOutcome: 'TBD',
    window: '2025',
    seed: 'TBD',
  },
];

export type WorldTemplate = Record<string, unknown>;