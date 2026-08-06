import hashlib

from sim_shared import canonical_json, chain_hash, idempotency_key
from sim_shared.rng import RNGRegistry, SeededRNG
from sim_shared.cost import CostMeter, CostLedgerEntry


def test_canonical_json_key_order_ignored():
    assert canonical_json({"b": 1, "a": [3, 2]}) == canonical_json({"a": [3, 2], "b": 1})


def test_canonical_json_matches_substrate_ts_shape():
    # Same shape the TS contract produces: sorted keys, no whitespace.
    assert canonical_json({"a": 1, "b": {"c": 2}}) == '{"a":1,"b":{"c":2}}'


def test_chain_hash_is_sha256_64hex():
    body = canonical_json({"family": "stream", "kind": "post", "payload": {"text": "hi"}})
    h = chain_hash("0" * 64, body)
    assert len(h) == 64
    assert h == hashlib.sha256(("0" * 64 + body).encode()).hexdigest()


def test_idempotency_key_format():
    assert idempotency_key("run-1", "call-9", 2) == "run-1:call-9:2"


def test_rng_deterministic_and_independent_streams():
    a = list(SeededRNG(42, "a").next().normal(size=3))
    b = list(SeededRNG(42, "a").next().normal(size=3))
    assert a == b
    other = list(SeededRNG(42, "b").next().normal(size=3))
    assert a != other


def test_registry_derive_distinct_child_seeds():
    reg = RNGRegistry(7)
    s0 = reg.generator("m0").normal(size=100)
    s1 = reg.generator("m1").normal(size=100)
    assert list(s0) != list(s1)
    # reproducibility
    assert list(RNGRegistry(7).generator("m0").normal(size=100)) == list(s0)


def test_cost_meter_exclusive_buckets_and_summary():
    meter = CostMeter("R1")
    meter.record("a", 0, "tiny", input_tokens=10, cached_input_tokens=5, output_tokens=2)
    meter.record("a", 1, "tiny", input_tokens=1, cached_input_tokens=0, output_tokens=1)
    meter.record("b", 1, "tiny", input_tokens=4, cached_input_tokens=2, output_tokens=4)
    s = meter.summarize()
    assert s.total_input_tokens == 15
    assert s.total_cached_tokens == 7
    assert s.total_output_tokens == 7
    # buckets are exclusive: totals never double-count cached
    assert s.total_tokens == 15 + 7 + 7
    assert s.per_agent_tokens["a"] == 19
    entry = meter.entries()[0]
    assert isinstance(entry, CostLedgerEntry)
    assert entry.total_tokens == 17