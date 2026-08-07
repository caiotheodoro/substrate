"""S4b real-surrogate contamination probe — failure-mode safety.

Gate: a total network outage must be loud (RuntimeError from run_all, a
non-zero network_failures count in the artifact), never silently
indistinguishable from a genuinely clean 0% false-fire result.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from trust.forge.studies.s4b_real_surrogate import PROBE_FAILURE_SENTINEL, real_llm_complete_fn, run_all


class TestFailureIsLoud:
    def test_unreachable_endpoint_returns_sentinel_and_records_failure(self):
        from trust.forge.generators import ToolUseTaskGenerator

        task = ToolUseTaskGenerator().generate(n=1)[0]
        failures: list[str] = []
        # port 1 is privileged / never listening in this environment —
        # connection is refused immediately, no real network needed.
        complete_fn = real_llm_complete_fn("http://127.0.0.1:1", "any-model", "any-key", failures=failures)
        result = complete_fn(task, "hint text")
        assert result == PROBE_FAILURE_SENTINEL
        assert len(failures) == 1
        assert task.task_id in failures[0]

    def test_run_all_raises_when_every_probe_fails(self, tmp_path):
        with pytest.raises(RuntimeError, match="masked outage"):
            run_all(tmp_path, n_tasks=3)
        # the artifact is still written for inspection even though the run
        # itself is flagged invalid
        assert (tmp_path / "s4b-real-surrogate.json").exists()
        written = json.loads((tmp_path / "s4b-real-surrogate.json").read_text())
        assert written["n_network_failures"] == 3
        assert written["n_tasks"] == 3

    def test_run_all_succeeds_and_reports_zero_failures_against_a_working_endpoint(self, tmp_path, monkeypatch):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                json.loads(self.rfile.read(length))
                resp = {"choices": [{"message": {"content": "I have no idea what the values are."}}]}
                data = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setenv("MODEL_PROVIDER_BASE_URL", f"http://127.0.0.1:{port}")
            monkeypatch.setenv("MODEL_PROVIDER_MODEL_ID", "mock-model")
            monkeypatch.setenv("MODEL_PROVIDER_API_KEY", "mock-key")
            result = run_all(tmp_path, n_tasks=3)
            assert result["n_network_failures"] == 0
            assert result["network_failures"] == []
        finally:
            server.shutdown()
            thread.join(timeout=2)
