from sim_probes import (
    CalibrationCorpus,
    ProbeReport,
    _demo_events,
    alliance_rate,
    interruption_rate,
    latency_distribution,
    lurking_rate,
    run_all_probes,
    silence_misreading_rate,
)


def test_run_all_probes_with_fixture():
    events = _demo_events(12, seed=3)
    results = run_all_probes(events, total_rounds=20)
    names = {r.probe for r in results}
    assert names == {
        "latency-mean",
        "latency-p95",
        "lurking",
        "interruption",
        "silence-misreading",
        "alliance",
    }
    assert all(r.passed for r in results)


def test_lurking_rate_counts_silence():
    events = [
        {"kind": "post", "payload": {"agent": "A"}},
        {"kind": "silence", "payload": {"agent": "B"}},
        {"kind": "reply", "payload": {"agent": "A"}},
    ]
    rate = lurking_rate(events, total_rounds=3)
    assert round(rate, 3) == round(1 / 3, 3)


def test_latency_distribution_returns_mean_and_p95():
    events = [
        {"kind": "post", "payload": {"agent": "A", "t": 0}},
        {"kind": "reply", "payload": {"agent": "A", "t": 2}},
        {"kind": "reply", "payload": {"agent": "A", "t": 4}},
    ]
    mean, p95 = latency_distribution(events)
    assert mean == 2.0
    assert p95 >= 2.0


def test_interruption_is_bounded():
    events = [
        {"kind": "post", "payload": {"agent": "A"}},
        {"kind": "reply", "payload": {"agent": "B"}},
        {"kind": "post", "payload": {"agent": "A"}},
    ]
    assert interruption_rate(events) <= 1.0


def test_silence_misreading_detected():
    events = [
        {"kind": "silence", "payload": {"agent": "B"}},
        {"kind": "confront", "payload": {"agent": "A"}},
        {"kind": "post", "payload": {"agent": "C"}},
    ]
    assert silence_misreading_rate(events) == 1.0


def test_calibration_corpus_v1():
    corpus = CalibrationCorpus()
    assert corpus.n == 18
    stats = corpus.stats()
    assert stats["version"] == "v1"
    assert stats["mean_rounds"] > 0
    assert stats["p95_rounds"] <= 4


def test_probe_report_roundtrips_json(tmp_path):
    import json

    report = ProbeReport(run_all_probes(_demo_events(10)), corpus=CalibrationCorpus())
    path = report.write(tmp_path / "probe-report.json")
    blob = json.loads(path.read_text())
    assert blob["version"] == "probe-report-v1"
    assert blob["total"] == 6
    assert blob["calibration"]["n"] == 18
    assert "passed" in blob