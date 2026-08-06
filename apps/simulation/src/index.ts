// @substrate/simulation — calibrated behavioral simulation.
// Spec: apps/simulation/SPEC.md
//
// Substrate bridge (M9): exports the shock scenarios and sim-run events in
// the frozen @substrate contract shapes. The Python sim (py/) is the engine;
// this module is the read-only bridge OUT of the sim into substrate.

export * from './scenarios.js';
export * from './bridge.js';