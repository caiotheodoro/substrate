"""S4b — the real-surrogate contamination probe (HANDOFF open path #5).

S4 (``s4_contamination_roc.py``) validates the leak-probe MECHANISM against
a synthetic leaked-knowledge-base membership check. This script runs the
same probe shape against a REAL model (``run_llm_leak_probes`` in
``trust.forge.contamination``): the model sees only ``format_hint`` — tool
names and arg keys, values withheld — and is asked to fill in the values.
This is the actual Gemini-3 scenario from the ARC-AGI-3 report: a
verification model reproduced ARC's integer-to-color mapping despite never
being told it, because the mapping was in its training data.

A real, never-leaked model + never-leaked tasks should fire on ~0% of
probes (it has no way to know the withheld values); that's the honest
baseline this script measures. It is NOT a leak-rate sweep like S4 — there
is only one leak rate here (0%, nothing was actually leaked to the real
model), and the finding is the false-fire rate itself.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from trust.forge.contamination import format_hint, run_llm_leak_probes
from trust.forge.generators import ToolUseTaskGenerator
from trust.forge.study import write_json
from trust.forge.task import ForgeTask


# A network/parse failure and a genuinely honest "I don't know" must never
# look the same in the completion text — a total outage would otherwise
# produce fired=False on every task, which is exactly the same shape as
# the honest clean-baseline result this script exists to measure. This
# sentinel can't be mistaken for a real model answer.
PROBE_FAILURE_SENTINEL = "__PROBE_NETWORK_OR_PARSE_FAILURE__"


def real_llm_complete_fn(base_url: str, model: str, api_key: str, *, failures: list[str]):
    def complete_fn(task: ForgeTask, hint: str) -> str:
        prompt = (
            f"Here is the STRUCTURE of a tool-call sequence (tool names and "
            f"argument keys only, values omitted):\n\n{hint}\n\n"
            "Fill in plausible exact values for every argument, based only "
            "on what you already know. Reply with just the values."
        )
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 200,
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            failures.append(f"{task.task_id}: {exc}")
            return PROBE_FAILURE_SENTINEL

    return complete_fn


def run_all(out_dir: Path, *, n_tasks: int = 20) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = ToolUseTaskGenerator().generate(n=n_tasks)

    base_url = os.environ.get("MODEL_PROVIDER_BASE_URL", "http://localhost:11434") + "/v1"
    model = os.environ.get("MODEL_PROVIDER_MODEL_ID", "qwen2.5:3b")
    api_key = os.environ.get("MODEL_PROVIDER_API_KEY", "ollama")
    failures: list[str] = []
    complete_fn = real_llm_complete_fn(base_url, model, api_key, failures=failures)

    probes = run_llm_leak_probes(tasks, complete_fn=complete_fn)
    fired = [p for p in probes if p.fired]
    n_network_failures = len(failures)
    results = {
        "model": model,
        "n_tasks": len(tasks),
        "n_fired": len(fired),
        "false_fire_rate": round(len(fired) / max(len(tasks), 1), 4),
        "n_network_failures": n_network_failures,
        "network_failures": failures[:10],  # bounded sample, not every one
        "probes": [p.as_dict() for p in probes],
    }
    write_json(out_dir / "s4b-real-surrogate.json", results)
    print(json.dumps({k: v for k, v in results.items() if k != "probes"}, indent=2))
    if n_network_failures == len(tasks):
        raise RuntimeError(
            f"all {len(tasks)} probes failed to reach {base_url} — the 0% "
            "false-fire result this script would otherwise report is not a "
            "real measurement, it's a masked outage. Artifact still "
            "written for inspection; the run itself is not a valid result."
        )
    elif n_network_failures > 0:
        print(f"WARNING: {n_network_failures}/{len(tasks)} probes failed to reach the endpoint — "
              "see network_failures in the artifact. false_fire_rate is computed over ALL tasks, "
              "including failed ones (which count as fired=False), so a high failure count "
              "silently drags the rate toward 0 without that being a real finding.")
    return results


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--out", default="docs/validation/studies")
    p.add_argument("--tasks", type=int, default=20)
    args = p.parse_args()
    run_all(Path(args.out), n_tasks=args.tasks)
    sys.exit(0)
