"""StackOpt v1 data shapes. See STACKOPT_CONTRACTS_V1.md for invariants."""

from typing import Final, Generic, Literal, NotRequired, TypedDict, TypeVar

from .diagnostics import Diagnostic

SCHEMA_VERSION: Final = 1
FREECAD_UNCONFIGURED = "unconfigured"
DecimalText = str
ValueT = TypeVar("ValueT")
UnitT = TypeVar("UnitT")
ScoreT = TypeVar("ScoreT")
Scope = Literal["single_chain"]
Side = Literal["minimum", "maximum"]
AllocationStatus = Literal["complete", "infeasible", "incomplete", "zero_tested"]
ToleranceSource = Literal["manual", "cad", "option"]


class Quantity(TypedDict, Generic[UnitT]):
    value: DecimalText
    unit: UnitT


Length = Quantity[Literal["mm", "m", "in"]]
Temperature = Quantity[Literal["degC", "K"]]
ExpansionCoefficient = Quantity[Literal["1/K"]]


class CalloutRef(TypedDict):
    document_id: str
    dimension_id: str
    revision: NotRequired[str]
    configuration: NotRequired[str]


def callout_key(callout: CalloutRef) -> tuple[str, str, str | None, str | None]:
    """Identity shared by the resolver, evaluator and allocator."""
    return (
        callout["document_id"],
        callout["dimension_id"],
        callout.get("revision"),
        callout.get("configuration"),
    )


class Deviations(TypedDict, Generic[ValueT]):
    lower: ValueT
    upper: ValueT


class DrawingLimits(TypedDict, Generic[ValueT]):
    deviations: Deviations[ValueT]
    lower: ValueT
    upper: ValueT


class Sides(TypedDict, Generic[ValueT], total=False):
    minimum: ValueT
    maximum: ValueT


class Requirement(Sides[ValueT]):
    id: str


class ThermalModel(TypedDict, Generic[ValueT]):
    kind: Literal["linear_free_expansion"]
    reference: ValueT
    operating_min: ValueT
    operating_max: ValueT


class ChainTerm(TypedDict, Generic[ValueT]):
    logical_id: str
    coefficient: ValueT


class Chain(TypedDict, Generic[ValueT]):
    id: str
    terms: list[ChainTerm[ValueT]]


class ManualNominal(TypedDict):
    kind: Literal["manual"]
    length: Length
    source_ref: str


class CadTarget(TypedDict):
    adapter: str
    occurrence_path: list[str]
    configuration: str
    dimension_id: str


class CadNominal(TypedDict):
    kind: Literal["cad"]
    target: CadTarget


class CadBinding(TypedDict):
    logical_id: str
    target: CadTarget


class ManualTolerance(TypedDict):
    kind: Literal["manual"]
    deviations: Deviations[Length]
    source_ref: str


class CadTolerance(TypedDict):
    kind: Literal["cad"]


class DimensionSpec(TypedDict):
    logical_id: str
    physical_id: str
    callout: CalloutRef
    alpha: ExpansionCoefficient
    nominal: ManualNominal | CadNominal
    tolerance: ManualTolerance | CadTolerance


class Objective(TypedDict):
    basis: Literal["synthetic_penalty", "quoted_cost"]
    unit: str
    source_ref: str
    context: str


class OptionScore(TypedDict, Generic[ValueT]):
    value: ValueT
    source_ref: NotRequired[str]


class ToleranceOption(TypedDict, Generic[ValueT, ScoreT]):
    id: str
    deviations: Deviations[ValueT]
    score: NotRequired[OptionScore[ScoreT]]


class OptionGroup(TypedDict, Generic[ValueT, ScoreT]):
    callout: CalloutRef
    options: list[ToleranceOption[ValueT, ScoreT]]


class CaseDocument(TypedDict):
    kind: Literal["case"]
    schema_version: Literal[1]
    case_id: str
    scope: Scope
    chain: Chain[DecimalText]
    requirement: Requirement[Length]
    model: ThermalModel[Temperature]
    dimensions: list[DimensionSpec]
    option_groups: NotRequired[list[OptionGroup[Length, DecimalText]]]
    objective: NotRequired[Objective]


class CadDocumentRef(TypedDict):
    id: str
    state: Literal["saved", "modified", "unsaved", "unknown"]
    path: NotRequired[str]


class CadSource(TypedDict):
    adapter: str
    application: str
    application_version: str
    assembly: CadDocumentRef
    assembly_configuration: str
    occurrence_path: list[str]
    document: CadDocumentRef
    configuration: str
    dimension_id: str


class CadToleranceEvidence(TypedDict):
    native_type: NotRequired[int | str]
    native_status: NotRequired[dict[str, int | str]]


class SupportedCadTolerance(CadToleranceEvidence):
    status: Literal["supported"]
    deviations: Deviations[Length]


class UnresolvedCadTolerance(CadToleranceEvidence):
    status: Literal["missing", "unsupported", "drawing_only", "unavailable"]


class CadExtraction(TypedDict):
    kind: Literal["cad_extraction"]
    schema_version: Literal[1]
    logical_id: str
    diagnostics: list[Diagnostic]


class CadExtractionSuccess(CadExtraction):
    status: Literal["resolved"]
    source: CadSource
    nominal: Length
    tolerance: SupportedCadTolerance | UnresolvedCadTolerance


class CadExtractionFailure(CadExtraction):
    status: Literal["failed"]
    source: NotRequired[CadSource]


CadExtractionRecord = CadExtractionSuccess | CadExtractionFailure


class ResolvedDimension(TypedDict, Generic[ValueT]):
    logical_id: str
    physical_id: str
    callout: CalloutRef
    nominal: ValueT
    alpha: ValueT
    drawing_limits: DrawingLimits[ValueT]
    tolerance_source: ToleranceSource


class ResolvedProblem(TypedDict, Generic[ValueT]):
    scope: Scope
    chain: Chain[ValueT]
    requirement: Requirement[ValueT]
    model: ThermalModel[ValueT]
    dimensions: list[ResolvedDimension[ValueT]]
    option_groups: list[OptionGroup[ValueT, ValueT]]
    objective: NotRequired[Objective]


class SnapshotDocument(TypedDict):
    kind: Literal["snapshot"]
    schema_version: Literal[1]
    case: CaseDocument
    problem: ResolvedProblem[DecimalText]
    extraction_records: list[CadExtractionSuccess]
    diagnostics: list[Diagnostic]


class DimensionLimits(TypedDict, Generic[ValueT]):
    physical_id: str
    callout: CalloutRef
    tolerance_source: ToleranceSource
    limits: DrawingLimits[ValueT]


class BoundTerm(TypedDict, Generic[ValueT]):
    physical_id: str
    callout: CalloutRef
    coefficient: ValueT
    drawing_limit: Literal["lower", "upper"]
    expanded_length: ValueT
    contribution: ValueT


class BoundTrace(TypedDict, Generic[ValueT]):
    value: ValueT
    temperature: ValueT
    terms: list[BoundTerm[ValueT]]


class Evaluation(TypedDict, Generic[ValueT]):
    drawing_limits: list[DimensionLimits[ValueT]]
    lower_bound: BoundTrace[ValueT]
    upper_bound: BoundTrace[ValueT]
    margins: Sides[ValueT]
    meets_requirement: bool
    limiting_side: Side


class ResultContext(TypedDict):
    schema_version: Literal[1]
    source_kind: Literal["case", "snapshot"]
    case_id: str
    scope: Scope
    chain_id: str
    requirement: Requirement[DecimalText]
    model: ThermalModel[DecimalText]
    baseline: Evaluation[DecimalText]
    diagnostics: list[Diagnostic]


class AnalysisResult(ResultContext):
    kind: Literal["analysis_result"]


class SelectedOption(TypedDict, Generic[ValueT]):
    callout: CalloutRef
    option_id: str
    score: NotRequired[OptionScore[ValueT]]


class Candidate(TypedDict, Generic[ValueT]):
    index: int
    assignment: list[SelectedOption[ValueT]]
    evaluation: Evaluation[ValueT]
    total_score: NotRequired[ValueT]


class SearchBudget(TypedDict, Generic[ValueT], total=False):
    max_evaluations: int
    max_seconds: ValueT


class SearchEvidence(TypedDict, Generic[ValueT]):
    status: AllocationStatus
    total: int
    evaluated: int
    feasible: int
    budget: NotRequired[SearchBudget[ValueT]]
    stop_reason: NotRequired[Literal["evaluation_limit", "time_limit", "interrupted"]]


class Ranking(TypedDict):
    status: Literal["unranked", "complete", "provisional"]
    objective: NotRequired[Objective]
    reason: NotRequired[Literal["no_objective", "missing_scores", "no_option_groups"]]
    best_candidate_indices: list[int]


class ClosestCandidate(TypedDict, Generic[ValueT]):
    qualification: Literal["closest_tested", "closest_so_far"]
    maximum_violation: ValueT
    candidate: Candidate[ValueT]


class CalloutChange(TypedDict, Generic[ValueT]):
    callout: CalloutRef
    option_id: str
    before: Deviations[ValueT]
    after: Deviations[ValueT]


class ContributionChange(TypedDict, Generic[ValueT]):
    physical_id: str
    baseline_contribution: ValueT
    candidate_contribution: ValueT


class MarginChange(TypedDict, Generic[ValueT]):
    baseline_margin: ValueT
    candidate_margin: ValueT
    margin_delta: ValueT
    baseline_temperature: ValueT
    candidate_temperature: ValueT
    same_temperature_delta: ValueT
    governing_temperature_delta: ValueT
    terms: list[ContributionChange[ValueT]]


class CandidateExplanation(TypedDict, Generic[ValueT]):
    candidate_index: int
    role: Literal["selected", "provisional_best", "closest_tested", "closest_so_far"]
    callout_changes: list[CalloutChange[ValueT]]
    margins: Sides[MarginChange[ValueT]]


class AllocationResult(ResultContext):
    kind: Literal["allocation_result"]
    search: SearchEvidence[DecimalText]
    feasible_candidates: list[Candidate[DecimalText]]
    ranking: Ranking
    closest: NotRequired[ClosestCandidate[DecimalText]]
    explanation: NotRequired[CandidateExplanation[DecimalText]]
