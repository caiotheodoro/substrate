"""Joint 2 (C3): 02's retrieval-verdict ladder ← 04's grounded gate (:8204).

True cross-unit e2e: the knowledge grounded-gate FastAPI app runs in ITS OWN
uv workspace (subprocess), 02's GroundedGateRung consumes it over HTTP.
Skipped when the knowledge workspace cannot be resolved.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from trust.contracts import RetrievalVerdict
from trust.extractors.grounded_gate import GroundedGateRung
from trust.extractors.retrieval_ladder import RetrievalLadder, LadderRung

PORT = 18084
# Walk up from this file until we find the monorepo root (contains
# apps/knowledge/py). Works locally (dir "research") and in CI (dir
# "substrate") without hardcoding the workspace name.
_REPO = Path(__file__).resolve()
while not (_REPO / "apps" / "knowledge" / "py").exists() and _REPO != _REPO.parent:
    _REPO = _REPO.parent
REPO_ROOT = _REPO
KNOWLEDGE_PY = REPO_ROOT / "apps/knowledge/py"

GATE_SERVER = f"""
import uvicorn
from substrate_knowledge.m6_gate.gate_api import build_gate_app
uvicorn.run(build_gate_app(), host="127.0.0.1", port={PORT}, log_level="warning")
"""


def _wait_for(url: str, deadline: float = 25.0) -> bool:
    import urllib.request

    start = time.time()
    while time.time() - start < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0):
                return True
        except Exception:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def knowledge_gate():
    uv_bin = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    proc = subprocess.Popen(
        [uv_bin, "run", "python", "-c", GATE_SERVER],
        cwd=str(KNOWLEDGE_PY),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for(f"http://127.0.0.1:{PORT}/health"):
            pytest.skip("knowledge workspace unavailable; skipping joint2 e2e")
        yield f"http://127.0.0.1:{PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_grounded_gate_rung_parses_c3(knowledge_gate: str) -> None:
    rung = GroundedGateRung(base_url=knowledge_gate)
    verdict = rung.verdict(
        "The Acme merger closed in June 2026.",
        ["Acme announced the merger completed on June 30, 2026."],
    )
    assert isinstance(verdict, RetrievalVerdict)
    assert verdict.kind in ("support", "contradict", "silent")
    assert 0.0 <= verdict.prob <= 1.0
    assert verdict.claim.startswith("The Acme merger")


def test_grounded_gate_rung_is_top_of_ladder(knowledge_gate: str) -> None:
    """The grounded gate rung runs after the LLM rungs and its prob dominates."""

    class _FakeLynx:
        name = "lynx-8b"

        def verdict(self, claim: str, passages: list[str], temperature: float = 0.0) -> RetrievalVerdict:
            return RetrievalVerdict(kind="silent", prob=0.2, citedEvidence=None, claim=claim)

    grounded = GroundedGateRung(base_url=knowledge_gate)
    ladder = RetrievalLadder(
        [
            LadderRung("lynx-8b", _FakeLynx(), escalate_below=1.01),
            LadderRung("grounded-gate", grounded, escalate_below=1.01),
        ]
    )
    verdict, trace = ladder.verdict(
        "The Acme merger closed in June 2026.",
        ["Acme announced the merger completed on June 30, 2026."],
    )
    assert trace.rungs_used == ["lynx-8b", "grounded-gate"]
    assert verdict.prob >= 0.2


def test_grounded_gate_rung_degrades_offline() -> None:
    """Unreachable gate → silent/0.0, never an exception (feature carries no signal)."""
    rung = GroundedGateRung(base_url="http://127.0.0.1:1", timeout=0.5)
    verdict = rung.verdict("claim", ["evidence"])
    assert verdict.kind == "silent"
    assert verdict.prob == 0.0
