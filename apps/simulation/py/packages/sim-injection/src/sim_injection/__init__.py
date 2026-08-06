"""M6 — Injection library (A-S-23 spec, A-S-24 scenarios, A-S-25 runtime).

The 4 shock scenarios are wired to the G-02 @substrate/scenarios seeds via
`scenarios.mirror.json`, a regenerable, verified mirror of the frozen TS data
(scripts/verify_mirror.mjs checks it against the TS source at build time).
"""

from .spec import SHOCK_SPEC_SCHEMA, InjectionSpec, validate_shock_spec
from .scenarios import (
    SCENARIOS,
    ShockScenarioRef,
    get_scenario,
    list_scenarios,
    scenario_for_dataset,
)
from .runtime import InjectionRuntime, build_shock_seed

__all__ = [
    "SHOCK_SPEC_SCHEMA",
    "InjectionSpec",
    "validate_shock_spec",
    "SCENARIOS",
    "ShockScenarioRef",
    "get_scenario",
    "list_scenarios",
    "scenario_for_dataset",
    "InjectionRuntime",
    "build_shock_seed",
]