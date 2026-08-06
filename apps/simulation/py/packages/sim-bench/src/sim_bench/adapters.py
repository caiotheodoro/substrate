"""Adapter loading shortcuts for simbench CLI/service."""

from sim_engine import discover_entrypoints, list_adapters, get_adapter, register_adapter


def default_adapters() -> dict:
    discover_entrypoints()
    if not list_adapters():
        from sim_engine.swarm_demo import CascadeBehaviourAdapter

        register_adapter(CascadeBehaviourAdapter())
    return {m: get_adapter(m) for m in list_adapters()}