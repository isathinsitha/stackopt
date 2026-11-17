"""Exact worst-case evaluation of a validated StackOpt v1 chain."""

from fractions import Fraction
from typing import Literal, NoReturn

from .contracts import (
    BoundTerm,
    BoundTrace,
    DimensionLimits,
    Evaluation,
    ResolvedDimension,
    ResolvedProblem,
    Side,
    Sides,
    ThermalModel,
)
from .diagnostics import ContractError, ExitStatus

_PhysicalTerm = tuple[ResolvedDimension[Fraction], Fraction]
_Bounds = tuple[BoundTrace[Fraction], BoundTrace[Fraction]]


def _invalid_problem(message: str) -> NoReturn:
    raise ContractError({
        "code": "internal.failure",
        "severity": "error",
        "message": message,
        "recovery": "Check the validated problem and how any candidate limits were applied.",
    }, ExitStatus.EXECUTION_FAILURE)


def _compile_chain(problem: ResolvedProblem[Fraction]) -> list[_PhysicalTerm]:
    by_logical_id = {dimension["logical_id"]: dimension for dimension in problem["dimensions"]}
    by_physical_id: dict[str, _PhysicalTerm] = {}
    for term in problem["chain"]["terms"]:
        dimension = by_logical_id[term["logical_id"]]
        physical_id = dimension["physical_id"]
        first, coefficient = by_physical_id.get(physical_id, (dimension, Fraction(0)))
        if first is not dimension and (
            first["nominal"] != dimension["nominal"]
            or first["alpha"] != dimension["alpha"]
            or first["callout"] != dimension["callout"]
            or first["drawing_limits"] != dimension["drawing_limits"]
        ):
            _invalid_problem(f"Conflicting definitions for physical dimension {physical_id!r}.")
        by_physical_id[physical_id] = first, coefficient + term["coefficient"]
    return list(by_physical_id.values())


def _bounds_at_temperature(
    terms: list[_PhysicalTerm], model: ThermalModel[Fraction], temperature: Fraction,
) -> _Bounds:
    if model["kind"] != "linear_free_expansion":
        _invalid_problem("The evaluator requires the linear free-expansion model.")

    delta = temperature - model["reference"]
    lower_terms: list[BoundTerm[Fraction]] = []
    upper_terms: list[BoundTerm[Fraction]] = []
    for dimension, coefficient in terms:
        factor = 1 + dimension["alpha"] * delta
        if factor <= 0:
            _invalid_problem(f"Nonpositive thermal expansion factor for {dimension['physical_id']!r}.")
        if coefficient == 0:
            continue

        limits = dimension["drawing_limits"]
        expanded = {"lower": limits["lower"] * factor, "upper": limits["upper"] * factor}
        lower_limit: Literal["lower", "upper"] = "lower" if coefficient > 0 else "upper"
        upper_limit: Literal["lower", "upper"] = "upper" if coefficient > 0 else "lower"
        for chosen, trace in ((lower_limit, lower_terms), (upper_limit, upper_terms)):
            length = expanded[chosen]
            trace.append({
                "physical_id": dimension["physical_id"],
                "callout": dimension["callout"].copy(),
                "coefficient": coefficient,
                "drawing_limit": chosen,
                "expanded_length": length,
                "contribution": coefficient * length,
            })

    # Compute each bound from the same contributions the caller receives.
    return (
        {"value": sum((term["contribution"] for term in lower_terms), Fraction(0)),
         "temperature": temperature, "terms": lower_terms},
        {"value": sum((term["contribution"] for term in upper_terms), Fraction(0)),
         "temperature": temperature, "terms": upper_terms},
    )


def evaluate_at_temperature(problem: ResolvedProblem[Fraction], temperature: Fraction | int) -> _Bounds:
    """Return (lower, upper) bound traces at an exact temperature in °C.

    The temperature must be within the validated operating interval, inclusive.
    A point query gives the signed stack-ups for that temperature.
    """
    if isinstance(temperature, bool) or not isinstance(temperature, (Fraction, int)):
        raise TypeError("Temperature must be an exact Fraction or integer in degrees Celsius.")
    temperature = Fraction(temperature)
    model = problem["model"]
    if not model["operating_min"] <= temperature <= model["operating_max"]:
        raise ValueError("Temperature is outside the validated operating interval.")
    return _bounds_at_temperature(_compile_chain(problem), model, temperature)


def evaluate(problem: ResolvedProblem[Fraction]) -> Evaluation[Fraction]:
    """Return the operating envelope, signed traces and declared clearance margins.

    Positive thermal factors preserve the order of the two drawing limits, so
    each bound uses the same corner of the physical dimensions at every
    temperature. The length at that corner is affine in the common temperature.
    A sum of such terms is affine too, with extrema at the operating endpoints.
    """
    terms = _compile_chain(problem)
    model = problem["model"]
    cold, hot = model["operating_min"], model["operating_max"]
    lower, upper = _bounds_at_temperature(terms, model, cold)
    # Strict comparisons retain the lower operating endpoint on an exact tie.
    if hot != cold:
        hot_lower, hot_upper = _bounds_at_temperature(terms, model, hot)
        if hot_lower["value"] < lower["value"]:
            lower = hot_lower
        if hot_upper["value"] > upper["value"]:
            upper = hot_upper

    requirement = problem["requirement"]
    margins: Sides[Fraction] = {}
    if "minimum" in requirement:
        margins["minimum"] = lower["value"] - requirement["minimum"]
    if "maximum" in requirement:
        margins["maximum"] = requirement["maximum"] - upper["value"]
    limiting_side: Side = "minimum"
    if "minimum" not in margins or ("maximum" in margins and margins["maximum"] < margins["minimum"]):
        limiting_side = "maximum"

    drawing_limits: list[DimensionLimits[Fraction]] = []
    for dimension, _ in terms:
        limits = dimension["drawing_limits"]
        drawing_limits.append({
            "physical_id": dimension["physical_id"],
            "callout": dimension["callout"].copy(),
            "tolerance_source": dimension["tolerance_source"],
            "limits": {"lower": limits["lower"], "upper": limits["upper"],
                       "deviations": limits["deviations"].copy()},
        })
    return {
        "drawing_limits": drawing_limits,
        "lower_bound": lower,
        "upper_bound": upper,
        "margins": margins,
        "meets_requirement": margins[limiting_side] >= 0,
        "limiting_side": limiting_side,
    }
