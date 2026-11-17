"""In-process interface between the extraction handler and an optional CAD adapter."""

from collections.abc import Sequence
from typing import Protocol, TypeVar

BindingT = TypeVar("BindingT", contravariant=True)
RecordT = TypeVar("RecordT", covariant=True)


class CadAdapter(Protocol[BindingT, RecordT]):
    """Read validated bindings from the active assembly without editing it."""

    def extract_active(self, bindings: Sequence[BindingT], /) -> Sequence[RecordT]:
        """Return one plain-data outcome per binding, correlated by logical ID."""
        ...
