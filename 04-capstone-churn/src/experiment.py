"""Experiment design and analysis for a two-arm conversion test.

Written out by hand rather than called from statsmodels, because the point of
this module is to show that I know what the formulas are and what they assume.
`tests/test_experiment.py` validates every function here against statsmodels and
scipy, so "by hand" does not mean "unchecked".

Contents:
    required_sample_size   how many users per arm, before you run the test
    minimum_detectable_effect   what you can detect given the traffic you have
    analyse_two_proportions     the test, the interval, and the effect size
    revenue_impact              the result translated into money, with assumptions
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy import stats

__all__ = [
    "required_sample_size",
    "minimum_detectable_effect",
    "analyse_two_proportions",
    "revenue_impact",
    "TestResult",
    "RevenueImpact",
]


def _z(p: float) -> float:
    """The standard normal quantile. scipy, because hand-rolling this is silly."""
    return float(stats.norm.ppf(p))


# -----------------------------------------------------------------------------
# Design: how big does the test need to be?
# -----------------------------------------------------------------------------

def required_sample_size(
    baseline_rate: float,
    absolute_lift: float,
    alpha: float = 0.05,
    power: float = 0.80,
    two_sided: bool = True,
) -> int:
    """Users required **per arm** to detect `absolute_lift` on `baseline_rate`.

    Uses the normal approximation with separate variances under the null
    (pooled) and the alternative (unpooled):

        n = [ z_(1-a/2)*sqrt(2*p_bar*(1-p_bar)) + z_(1-b)*sqrt(p1(1-p1)+p2(1-p2)) ]^2
            / delta^2

    The textbook shortcut `n = 2(z_a + z_b)^2 * p_bar(1-p_bar) / delta^2` uses the
    pooled variance for both terms. Because p(1-p) is concave, the average of
    p1(1-p1) and p2(1-p2) is always at most p_bar(1-p_bar), so the shortcut always
    asks for *at least* as many users as this formula does -- it errs on the safe
    side, and the gap widens as the lift grows. At a 20% baseline and a 10 point
    lift the difference is 295 against 294 users per arm; at the small lifts real
    tests are powered for it is invisible. Either is defensible. This one is used
    because it is the exact normal-approximation expression rather than a
    simplification of it.

    Why this matters more than the p-value at the end: a test powered at 50%
    will, half the time, fail to detect a real effect that is exactly the size
    you cared about. Running an underpowered test and reading "not significant"
    as "no effect" is the single most common experimentation error.

    Args:
        baseline_rate: the control arm's conversion rate, as a proportion.
        absolute_lift: the effect you want to be able to detect, in percentage
            points expressed as a proportion (0.02 means 2 points, e.g. 5% -> 7%).
        alpha: false positive rate.
        power: 1 - false negative rate.
        two_sided: a one-sided test needs fewer users but can only ever conclude
            "better", never "worse". Almost always keep this True.

    Raises:
        ValueError: if the rates are not valid proportions.
    """
    p1 = baseline_rate
    p2 = baseline_rate + absolute_lift
    if not 0 < p1 < 1:
        raise ValueError(f"baseline_rate must be in (0, 1), got {p1}")
    if not 0 < p2 < 1:
        raise ValueError(
            f"baseline_rate + absolute_lift must be in (0, 1), got {p2}. "
            "A lift that pushes the treatment rate past 100% is not a test, "
            "it is a typo."
        )
    if absolute_lift == 0:
        raise ValueError("absolute_lift of 0 requires infinite sample")

    p_bar = (p1 + p2) / 2
    z_alpha = _z(1 - alpha / 2) if two_sided else _z(1 - alpha)
    z_beta = _z(power)

    numerator = (
        z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    return math.ceil(numerator / absolute_lift**2)


def minimum_detectable_effect(
    baseline_rate: float,
    n_per_arm: int,
    alpha: float = 0.05,
    power: float = 0.80,
    two_sided: bool = True,
) -> float:
    """The smallest absolute lift detectable with `n_per_arm` users.

    This is the question a stakeholder actually asks, phrased the other way
    round: they do not have a free choice of sample size, they have however
    much traffic they have, and they want to know what it buys them.

    Solved numerically by inverting `required_sample_size`, because the closed
    form of the unpooled expression is unpleasant and a bisection over a
    monotone function is both shorter and easier to check.
    """
    if n_per_arm < 1:
        raise ValueError("n_per_arm must be >= 1")

    lo, hi = 1e-6, min(0.5, 1 - baseline_rate - 1e-9)
    if hi <= lo:
        raise ValueError(f"baseline_rate of {baseline_rate} leaves no room for a lift")

    # required_sample_size decreases monotonically in the lift, so bisect on it.
    if required_sample_size(baseline_rate, hi, alpha, power, two_sided) > n_per_arm:
        return float("nan")  # even the largest plausible effect is undetectable

    for _ in range(200):
        mid = (lo + hi) / 2
        if required_sample_size(baseline_rate, mid, alpha, power, two_sided) > n_per_arm:
            lo = mid
        else:
            hi = mid
    return hi


# -----------------------------------------------------------------------------
# Analysis: what did the test say?
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class TestResult:
    """The result of a two-proportion test, with everything needed to read it."""

    control_n: int
    control_conversions: int
    treatment_n: int
    treatment_conversions: int
    control_rate: float
    treatment_rate: float
    absolute_lift: float
    relative_lift: float
    z_statistic: float
    p_value: float
    ci_low: float
    ci_high: float
    confidence: float
    significant: bool
    observed_power: float = field(default=float("nan"))

    def summary(self) -> str:
        """A paragraph a non-technical stakeholder can read without help."""
        direction = "higher" if self.absolute_lift > 0 else "lower"
        verdict = (
            f"significant at the {int((1 - self.confidence) * 100)}% level"
            if self.significant
            else "not statistically significant"
        )
        lines = [
            f"Control:   {self.control_conversions:,}/{self.control_n:,} "
            f"= {self.control_rate:.2%}",
            f"Treatment: {self.treatment_conversions:,}/{self.treatment_n:,} "
            f"= {self.treatment_rate:.2%}",
            "",
            f"Treatment is {abs(self.absolute_lift):.2%} ({abs(self.relative_lift):.1%} "
            f"relative) {direction}.",
            f"95% CI on the absolute difference: "
            f"[{self.ci_low:+.2%}, {self.ci_high:+.2%}]",
            f"z = {self.z_statistic:.3f}, p = {self.p_value:.4f} -> {verdict}.",
        ]
        if not self.significant:
            lines += [
                "",
                "Not significant does not mean no effect. The interval above is "
                "the honest statement: any true effect inside it is consistent "
                "with this data.",
            ]
        return "\n".join(lines)


def analyse_two_proportions(
    control_n: int,
    control_conversions: int,
    treatment_n: int,
    treatment_conversions: int,
    confidence: float = 0.95,
) -> TestResult:
    """Two-proportion z-test with a confidence interval on the difference.

    Two deliberate choices, both of them conventional and both worth stating:

    1. The **test statistic** uses the *pooled* proportion, because under the
       null hypothesis the two arms share one rate:

           z = (p1 - p2) / sqrt( p_bar (1 - p_bar) (1/n1 + 1/n2) )

    2. The **confidence interval** uses the *unpooled* variances, because the
       interval describes the difference without assuming the null:

           (p1 - p2) +/- z * sqrt( p1(1-p1)/n1 + p2(1-p2)/n2 )

    Mixing these up is the most common mistake in hand-rolled A/B analysis. It
    produces a p-value and an interval that disagree about whether zero is
    inside the interval.

    The interval is the number to lead with. A p-value answers "could this be
    noise?"; the interval answers "how big is it?", which is the question a
    decision actually depends on.
    """
    if control_n <= 0 or treatment_n <= 0:
        raise ValueError("both arms need at least one user")
    if not 0 <= control_conversions <= control_n:
        raise ValueError("control_conversions must be between 0 and control_n")
    if not 0 <= treatment_conversions <= treatment_n:
        raise ValueError("treatment_conversions must be between 0 and treatment_n")

    p1 = control_conversions / control_n
    p2 = treatment_conversions / treatment_n
    diff = p2 - p1

    p_pooled = (control_conversions + treatment_conversions) / (control_n + treatment_n)
    se_pooled = math.sqrt(p_pooled * (1 - p_pooled) * (1 / control_n + 1 / treatment_n))

    if se_pooled == 0:
        # Both arms at 0% or both at 100%. There is no effect to test and no
        # standard error to divide by; say so rather than returning NaN silently.
        z_stat, p_value = 0.0, 1.0
    else:
        z_stat = diff / se_pooled
        p_value = 2 * (1 - stats.norm.cdf(abs(z_stat)))

    se_unpooled = math.sqrt(
        p1 * (1 - p1) / control_n + p2 * (1 - p2) / treatment_n
    )
    z_crit = _z(1 - (1 - confidence) / 2)
    ci_low = diff - z_crit * se_unpooled
    ci_high = diff + z_crit * se_unpooled

    # Post-hoc power at the observed effect size. Reported for completeness but
    # treated with suspicion: post-hoc power computed from the observed effect
    # is a deterministic function of the p-value and tells you nothing new. The
    # number worth quoting is the power the test was *designed* for.
    if se_unpooled > 0 and diff != 0:
        observed_power = float(
            stats.norm.cdf(abs(diff) / se_unpooled - z_crit)
        )
    else:
        observed_power = float("nan")

    return TestResult(
        control_n=control_n,
        control_conversions=control_conversions,
        treatment_n=treatment_n,
        treatment_conversions=treatment_conversions,
        control_rate=p1,
        treatment_rate=p2,
        absolute_lift=diff,
        relative_lift=diff / p1 if p1 > 0 else float("nan"),
        z_statistic=z_stat,
        p_value=p_value,
        ci_low=ci_low,
        ci_high=ci_high,
        confidence=confidence,
        significant=p_value < (1 - confidence),
        observed_power=observed_power,
    )


# -----------------------------------------------------------------------------
# Translation: what is it worth?
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class RevenueImpact:
    """A money figure with its full interval and its assumptions attached."""

    point_estimate: float
    low_estimate: float
    high_estimate: float
    annual_population: int
    average_order_value: float
    assumptions: tuple[str, ...]

    def summary(self) -> str:
        lines = [
            f"Point estimate:  {self.point_estimate:>15,.0f} per year",
            f"95% range:       {self.low_estimate:>15,.0f} to {self.high_estimate:,.0f}",
            "",
            "Assumptions (each one is a way this number could be wrong):",
        ]
        lines += [f"  {i}. {a}" for i, a in enumerate(self.assumptions, 1)]
        return "\n".join(lines)


def revenue_impact(
    result: TestResult,
    annual_population: int,
    average_order_value: float,
    extra_assumptions: tuple[str, ...] = (),
) -> RevenueImpact:
    """Translate a conversion lift into annual revenue.

        annual revenue = absolute lift x annual population x average order value

    The arithmetic is trivial. What makes it useful or misleading is the
    assumptions, so they are returned alongside the number and printed with it,
    and the **interval** is carried through from the test rather than quietly
    dropped. A single-point revenue figure derived from a confidence interval
    that straddles zero is the most dangerous output in analytics: it looks
    precise and it is not.
    """
    if annual_population < 0:
        raise ValueError("annual_population cannot be negative")
    if average_order_value < 0:
        raise ValueError("average_order_value cannot be negative")

    scale = annual_population * average_order_value
    base = (
        f"Lift measured over {result.control_n + result.treatment_n:,} users "
        f"holds for all {annual_population:,} annual users.",
        f"Average order value stays at {average_order_value:,.0f}.",
        "The lift persists rather than decaying as novelty wears off.",
        "No cannibalisation of other channels or of future purchases.",
    )
    if not result.significant:
        base += (
            "The test was NOT significant, so the interval includes zero and "
            "this point estimate should not be used on its own.",
        )

    return RevenueImpact(
        point_estimate=result.absolute_lift * scale,
        low_estimate=result.ci_low * scale,
        high_estimate=result.ci_high * scale,
        annual_population=annual_population,
        average_order_value=average_order_value,
        assumptions=base + extra_assumptions,
    )
