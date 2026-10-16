"""Validate the hand-rolled statistics against statsmodels and scipy.

Writing the formulas out by hand demonstrates understanding. Checking them
against an established library demonstrates that the understanding is correct.
Both matter; neither is sufficient alone.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04-capstone-churn" / "src"))

from experiment import (  # noqa: E402
    analyse_two_proportions,
    minimum_detectable_effect,
    required_sample_size,
    revenue_impact,
)

statsmodels = pytest.importorskip("statsmodels.stats.proportion")
from statsmodels.stats.power import NormalIndPower  # noqa: E402
from statsmodels.stats.proportion import (  # noqa: E402
    confint_proportions_2indep,
    proportion_effectsize,
    proportions_ztest,
)

# -----------------------------------------------------------------------------
# The z-test
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "n1,x1,n2,x2",
    [
        (10_000, 500, 10_000, 600),      # 5.0% vs 6.0%, clearly significant
        (5_000, 250, 5_000, 265),        # 5.0% vs 5.3%, marginal
        (1_000, 50, 1_000, 52),          # tiny effect, tiny sample
        (50_000, 1_000, 50_000, 1_050),  # small effect, large sample
        (8_000, 400, 12_000, 660),       # unequal arms
    ],
)
def test_z_statistic_matches_statsmodels(n1, x1, n2, x2):
    """Our pooled z-test must match statsmodels' proportions_ztest exactly."""
    mine = analyse_two_proportions(n1, x1, n2, x2)
    # statsmodels orders the arms as given; we define the lift as treatment
    # minus control, so pass treatment first to match our sign convention.
    sm_z, sm_p = proportions_ztest([x2, x1], [n2, n1], alternative="two-sided")
    assert mine.z_statistic == pytest.approx(sm_z, rel=1e-9, abs=1e-12)
    assert mine.p_value == pytest.approx(sm_p, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("n1,x1,n2,x2", [(10_000, 500, 10_000, 600), (3_000, 90, 3_000, 120)])
def test_confidence_interval_matches_statsmodels_wald(n1, x1, n2, x2):
    """The unpooled (Wald) interval must match statsmodels' 'wald' method."""
    mine = analyse_two_proportions(n1, x1, n2, x2)
    lo, hi = confint_proportions_2indep(
        x2, n2, x1, n1, method="wald", compare="diff", alpha=0.05
    )
    assert mine.ci_low == pytest.approx(lo, rel=1e-7, abs=1e-10)
    assert mine.ci_high == pytest.approx(hi, rel=1e-7, abs=1e-10)


def test_interval_and_p_value_agree_about_zero():
    """A significant result must have an interval excluding zero, and vice versa.

    This is the regression test for mixing pooled and unpooled variances. The
    two are computed differently on purpose, so they can disagree at the margin;
    this checks they do not disagree in the cases that matter.
    """
    for n in (2_000, 20_000, 200_000):
        for extra in (0, 5, 20, 100):
            r = analyse_two_proportions(n, int(n * 0.05), n, int(n * 0.05) + extra)
            crosses_zero = r.ci_low <= 0 <= r.ci_high
            # Allow disagreement only in the narrow band near p = 0.05, where
            # the pooled and unpooled standard errors genuinely differ.
            if not (0.03 < r.p_value < 0.07):
                assert r.significant == (not crosses_zero), (
                    f"n={n} extra={extra} p={r.p_value:.4f} "
                    f"ci=[{r.ci_low:.5f},{r.ci_high:.5f}]"
                )


def test_identical_arms_give_null_result():
    r = analyse_two_proportions(10_000, 500, 10_000, 500)
    assert r.absolute_lift == 0
    assert r.p_value == pytest.approx(1.0)
    assert not r.significant
    assert r.ci_low < 0 < r.ci_high


def test_degenerate_zero_conversions_does_not_crash():
    """Both arms at 0% has no standard error. It must not return NaN silently."""
    r = analyse_two_proportions(1_000, 0, 1_000, 0)
    assert r.z_statistic == 0.0
    assert r.p_value == 1.0
    assert not r.significant


def test_relative_lift_is_relative_to_control():
    r = analyse_two_proportions(10_000, 500, 10_000, 600)
    assert r.control_rate == pytest.approx(0.05)
    assert r.treatment_rate == pytest.approx(0.06)
    assert r.absolute_lift == pytest.approx(0.01)
    assert r.relative_lift == pytest.approx(0.20)  # 5% -> 6% is a 20% relative lift


@pytest.mark.parametrize(
    "kwargs",
    [
        {"control_n": 0, "control_conversions": 0,
         "treatment_n": 10, "treatment_conversions": 1},
        {"control_n": 10, "control_conversions": 11,
         "treatment_n": 10, "treatment_conversions": 1},
        {"control_n": 10, "control_conversions": -1,
         "treatment_n": 10, "treatment_conversions": 1},
    ],
)
def test_invalid_inputs_raise(kwargs):
    with pytest.raises(ValueError):
        analyse_two_proportions(**kwargs)


# -----------------------------------------------------------------------------
# Sample size
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "baseline,lift",
    [(0.05, 0.01), (0.05, 0.005), (0.10, 0.02), (0.02, 0.004), (0.30, 0.05)],
)
def test_sample_size_is_close_to_statsmodels(baseline, lift):
    """Within 5% of statsmodels' effect-size-based calculation.

    They are not identical by construction: statsmodels powers the test on the
    arcsine-transformed effect size (Cohen's h), while this module uses the
    normal approximation on the raw proportions. Both are standard; they agree
    closely for the effect sizes anyone actually runs.
    """
    mine = required_sample_size(baseline, lift, alpha=0.05, power=0.80)
    sm = NormalIndPower().solve_power(
        effect_size=proportion_effectsize(baseline + lift, baseline),
        nobs1=None, alpha=0.05, power=0.80, ratio=1.0, alternative="two-sided",
    )
    assert mine == pytest.approx(sm, rel=0.05), f"mine={mine} statsmodels={sm:.0f}"


def test_smaller_effects_need_bigger_samples():
    sizes = [required_sample_size(0.05, d) for d in (0.02, 0.01, 0.005, 0.0025)]
    assert sizes == sorted(sizes), "sample size must increase as the effect shrinks"
    # Halving the effect should roughly quadruple n (n scales as 1/delta^2).
    assert sizes[2] / sizes[1] == pytest.approx(4, rel=0.15)


def test_more_power_needs_more_users():
    assert (required_sample_size(0.05, 0.01, power=0.90)
            > required_sample_size(0.05, 0.01, power=0.80))


def test_one_sided_needs_fewer_users():
    assert required_sample_size(0.05, 0.01, two_sided=False) < required_sample_size(0.05, 0.01)


@pytest.mark.parametrize("baseline,lift", [(0.20, 0.10), (0.05, 0.01), (0.40, 0.15), (0.10, 0.05)])
def test_shortcut_formula_never_asks_for_fewer_users(baseline, lift):
    """The pooled shortcut must always be >= the exact formula.

    p(1-p) is concave, so (p1(1-p1) + p2(1-p2))/2 <= p_bar(1-p_bar) for any p1, p2.
    The shortcut therefore errs on the safe side. The docstring in
    required_sample_size claims exactly this, so it gets a test -- an earlier
    version of that docstring claimed the opposite and was wrong.
    """
    mine = required_sample_size(baseline, lift)
    p_bar = baseline + lift / 2
    z_a, z_b = stats.norm.ppf(0.975), stats.norm.ppf(0.80)
    shortcut = math.ceil(2 * (z_a + z_b) ** 2 * p_bar * (1 - p_bar) / lift**2)
    assert shortcut >= mine, f"shortcut={shortcut} exact={mine}"
    # And the two should stay in the same ballpark, not diverge wildly.
    assert shortcut / mine < 1.25


@pytest.mark.parametrize(
    "baseline,lift",
    [(0.0, 0.01), (1.0, 0.01), (0.95, 0.10), (0.05, 0.0), (0.05, -0.10)],
)
def test_impossible_designs_raise(baseline, lift):
    with pytest.raises(ValueError):
        required_sample_size(baseline, lift)


# -----------------------------------------------------------------------------
# Minimum detectable effect
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "baseline,n",
    [(0.05, 10_000), (0.05, 50_000), (0.10, 5_000), (0.02, 100_000)],
)
def test_mde_round_trips_with_sample_size(baseline, n):
    """MDE inverts required_sample_size, so the round trip must close."""
    mde = minimum_detectable_effect(baseline, n)
    assert not math.isnan(mde)
    needed = required_sample_size(baseline, mde)
    assert needed <= n, f"MDE {mde:.5f} claims to need {needed} but we have {n}"
    # And it should be tight: a slightly smaller effect must need more than n.
    tighter = required_sample_size(baseline, mde * 0.95)
    assert tighter > n


def test_mde_shrinks_as_traffic_grows():
    mdes = [minimum_detectable_effect(0.05, n) for n in (5_000, 20_000, 80_000, 320_000)]
    assert mdes == sorted(mdes, reverse=True)


def test_mde_is_nan_when_nothing_is_detectable():
    assert math.isnan(minimum_detectable_effect(0.05, 1))


# -----------------------------------------------------------------------------
# Revenue translation
# -----------------------------------------------------------------------------

def test_revenue_impact_arithmetic():
    r = analyse_two_proportions(100_000, 5_000, 100_000, 6_000)  # +1.00 point
    impact = revenue_impact(r, annual_population=500_000, average_order_value=40.0)
    # 0.01 * 500,000 * 40 = 200,000
    assert impact.point_estimate == pytest.approx(0.01 * 500_000 * 40)
    assert impact.low_estimate < impact.point_estimate < impact.high_estimate
    assert len(impact.assumptions) >= 4


def test_revenue_impact_carries_the_interval_not_just_the_point():
    r = analyse_two_proportions(100_000, 5_000, 100_000, 6_000)
    impact = revenue_impact(r, 500_000, 40.0)
    scale = 500_000 * 40
    assert impact.low_estimate == pytest.approx(r.ci_low * scale)
    assert impact.high_estimate == pytest.approx(r.ci_high * scale)


def test_non_significant_result_is_flagged_in_the_assumptions():
    """A revenue number from a null result must say so in its own output."""
    r = analyse_two_proportions(1_000, 50, 1_000, 52)
    assert not r.significant
    impact = revenue_impact(r, 500_000, 40.0)
    assert any("NOT significant" in a for a in impact.assumptions)
    assert impact.low_estimate < 0 < impact.high_estimate


def test_summaries_are_human_readable():
    r = analyse_two_proportions(10_000, 500, 10_000, 600)
    text = r.summary()
    assert "5.00%" in text and "6.00%" in text
    assert "95% CI" in text
    impact = revenue_impact(r, 500_000, 40.0)
    assert "Assumptions" in impact.summary()
