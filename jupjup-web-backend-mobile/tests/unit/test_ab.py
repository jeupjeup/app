from __future__ import annotations

import json

import pytest

from jupjup.eval.ab import ABConfig, ArmConfig, paired_delta_ci, run_ab


def test_paired_bootstrap_matches_hand_calculated_constant_deltas() -> None:
    result = paired_delta_ci([0.0, 0.5], [0.25, 0.75], metric="x", iterations=100, seed=7)
    assert result.delta == 0.25
    assert result.ci_low == result.ci_high == 0.25
    assert (result.wins, result.losses, result.ties) == (2, 0, 0)
    assert result.sign_test_p == 0.5


def test_paired_bootstrap_rejects_unpaired_or_empty_samples() -> None:
    with pytest.raises(ValueError):
        paired_delta_ci([], [], metric="x")
    with pytest.raises(ValueError):
        paired_delta_ci([1.0], [1.0, 2.0], metric="x")


@pytest.mark.eval
def test_a0_vs_a0_has_zero_deltas_and_is_deterministic() -> None:
    config = ABConfig(
        mode="mock",
        split="dev",
        arms=[ArmConfig(name="A0"), ArmConfig(name="A0-copy")],
        bootstrap_iterations=100,
    )
    first = run_ab(config)
    second = run_ab(config)
    comparison = first.comparisons[0]
    assert comparison.deltas
    assert all(delta.delta == delta.ci_low == delta.ci_high == 0.0 for delta in comparison.deltas)
    first_json = json.dumps(first.deterministic_dict(), sort_keys=True)
    assert first_json == json.dumps(second.deterministic_dict(), sort_keys=True)
