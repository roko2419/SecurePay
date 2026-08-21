"""Courier-label validator — forgery checks + deterministic identification.

Library usage (stable interface):

    from label_validator import validate_label

    result = validate_label("label.pdf")
    if result.is_authentic and result.contains(expected_order_id):
        ...

See `label_validator.api` for the full public API. Everything below `api` is
implementation detail and may change.
"""

from .api import (
    CheckOutcome,
    Finding,
    LabelResult,
    validate_label,
    validate_labels,
)

# Lower-level building blocks, exposed for advanced/custom use.
from .pdf_model import LabelPDF
from .checks import run_all
from .identify import extract_awb, extract_delivery_partner

__version__ = "1.0.0"

__all__ = [
    # stable public API
    "validate_label",
    "validate_labels",
    "LabelResult",
    "CheckOutcome",
    "Finding",
    # advanced building blocks
    "LabelPDF",
    "run_all",
    "extract_awb",
    "extract_delivery_partner",
    "__version__",
]
