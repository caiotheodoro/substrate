"""B2 — uncertainty decomposition (epistemic vs aleatoric).

Synthetic fixture with KNOWN split:
- aleatoric samples: genuinely ambiguous tasks — every judge (including the
  strongest) shows high variance;
- epistemic samples: the weak judge is confused, the strong judge resolves
  it (variance collapses);
- confident samples: stable across the whole ladder.

The decomposition must recover the true split; the naive single-judge
high-entropy flag cannot (it conflates both into one bucket).
"""
from __future__ import annotations

import hashlib

from trust.confbench.uncertainty_decomposition import (
    decompose_uncertainty,
    naive_high_entropy_flags,
)

STRENGTHS = (0.0, 0.5, 1.0)


def _draw(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF


def judge_family(strength: float, sample_id: str, *, draw: int = 0) -> callable:
    """Synthetic judge ladder with a known epistemic/aleatoric split.

    - 'aleatoric-N' samples: variance >= 0.01 at EVERY strength.
    - 'epistemic-N' samples: variance >= 0.01 only at weak strengths; the
      strong judge (strength >= 0.5) is stable.
    - 'confident-N' samples: stable everywhere.
    """
    state = [0]

    def draw_one() -> float:
        state[0] += 1
        d = state[0]
        if sample_id.startswith("aleatoric"):
            return _draw(f"{sample_id}:{d}")
        if sample_id.startswith("epistemic"):
            if strength >= 0.5:
                return 0.5  # strong judge resolves it
            return _draw(f"{sample_id}:{d}")
        return 0.5  # confident

    return draw_one


def samples(n_each: int = 8) -> list[str]:
    out = []
    for i in range(n_each):
        out.append(f"aleatoric-{i}")
        out.append(f"epistemic-{i}")
        out.append(f"confident-{i}")
    return out


class TestDecomposition:
    def test_recovers_the_known_split(self):
        report = decompose_uncertainty(samples(), judge_family, samples_per_judge=6)
        assert report.epistemic_fraction > 0.2
        assert report.aleatoric_fraction > 0.2
        assert len(report.aleatoric_samples) == len(report.epistemic_samples)
        assert all(s.startswith("aleatoric") for s in report.aleatoric_samples)
        assert all(s.startswith("epistemic") for s in report.epistemic_samples)

    def test_resolution_curve_floor_is_aleatoric(self):
        report = decompose_uncertainty(samples(), judge_family, samples_per_judge=6)
        weak = report.resolution[STRENGTHS[0]]
        strong = report.resolution[STRENGTHS[-1]]
        assert strong < weak  # strong judge resolves epistemic variance
        assert strong > 0  # aleatoric variance survives at the top

    def test_naive_flag_conflates_epistemic_and_aleatoric(self):
        """The naive single-judge method cannot separate sources — it flags
        epistemic samples as if they were aleatoric (the hallucination
        misclassification the article warns about)."""
        judges = {sid: judge_family(STRENGTHS[0], sid) for sid in samples()}
        naive = naive_high_entropy_flags(
            list(judges),
            lambda sid: judges[sid](),  # one weak judge per sample, stateful
            samples=6,
        )
        # single-judge flags can't distinguish the two sources
        assert naive  # it flags something
        epi = [s for s in naive if s.startswith("epistemic")]
        ale = [s for s in naive if s.startswith("aleatoric")]
        assert epi and ale  # both sources land in the same bucket

    def test_report_serializes(self, tmp_path):
        report = decompose_uncertainty(samples(4), judge_family, samples_per_judge=4)
        out = tmp_path / "validation" / "uncertainty.json"
        report.write(out)
        assert out.exists()
        d = report.as_dict()
        assert set(d) == {
            "n_samples",
            "epistemic_fraction",
            "aleatoric_fraction",
            "n_aleatoric",
            "n_epistemic",
            "resolution",
        }
