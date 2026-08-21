"""Public API — the stable interface for using this package as a library.

Everything a consumer needs is here and re-exported from the package root:

    from label_validator import validate_label

    result = validate_label("label.pdf")
    result.verdict            # "LIKELY AUTHENTIC" | "SUSPICIOUS" | "LIKELY FORGED"
    result.is_authentic       # bool
    result.awb                # tracking number (str | None)
    result.delivery_partner   # carrier (str | None)
    result.raw_text           # full label text
    result.barcodes           # list[str]
    result.contains("400025") # lookup an expected value in the label
    result.to_dict()          # JSON-serializable dict

This module is the contract: these names, fields and shapes stay stable. The
implementation behind them (`checks`, `pdf_model`, `report`, `identify`) may
change freely without breaking callers.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

from .checks import run_all
from .identify import extract_awb, extract_delivery_partner
from .pdf_model import LabelPDF
from .report import Report

__all__ = [
    "validate_label",
    "validate_labels",
    "LabelResult",
    "CheckOutcome",
    "Finding",
]

# Separators a label may vary on; stripped (both sides) for LabelResult.contains.
# Keeps letters (any script) and digits; drops whitespace, common punctuation,
# and soft/zero-width characters (U+00AD, U+200B–U+200F, U+FEFF).
_SEPARATORS = re.compile(
    "[\\s\\-_/.,#:;()\u00ad\u200b\u200c\u200d\u200e\u200f\ufeff]+"
)


# --------------------------------------------------------------------------- #
# Public result types (stable shapes)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Finding:
    """One reason a check failed."""
    message: str
    where: str = ""
    evidence: str = ""
    critical: bool = False
    penalty: int | None = None


@dataclass(frozen=True)
class CheckOutcome:
    """The result of a single forgery check."""
    key: str
    title: str
    status: str            # "PASS" | "FAIL" | "INCONCLUSIVE"
    penalty: int
    summary: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


@dataclass(frozen=True)
class LabelResult:
    """The full outcome of validating one label — the object callers work with."""
    file: str
    verdict: str           # "LIKELY AUTHENTIC" | "SUSPICIOUS" | "LIKELY FORGED"
    score: int             # 0-100
    critical_hit: bool
    awb: str | None
    delivery_partner: str | None
    raw_text: str
    barcodes: list[str]
    checks: list[CheckOutcome]

    # -- convenience -------------------------------------------------------- #
    @property
    def is_authentic(self) -> bool:
        return self.verdict == "LIKELY AUTHENTIC"

    @property
    def is_forged(self) -> bool:
        return self.verdict == "LIKELY FORGED"

    def contains(self, value, *, normalize: bool = True) -> bool:
        """True if *value* appears in the label's text or barcodes.

        With ``normalize`` (default) the match ignores case and the separators
        labels vary on — whitespace, hyphens, dots, slashes, colons, commas, and
        soft/zero-width characters — so an expected ``"ORD-4408812"``,
        ``"400025"`` or ``"Manisha Tulsiani"`` is found regardless of the label's
        formatting. Letters (including non-Latin scripts) and digits are kept.
        Pass ``normalize=False`` for an exact substring match.
        """
        if value is None:
            return False
        haystack = self.raw_text + " " + " ".join(self.barcodes)
        needle = str(value)
        if normalize:
            squash = lambda s: _SEPARATORS.sub("", s).casefold()
            needle_n = squash(needle)
            return bool(needle_n) and needle_n in squash(haystack)
        return needle in haystack

    def to_dict(self) -> dict:
        """JSON-serializable dict (same shape the CLI emits with --json)."""
        return {
            "file": self.file,
            "score": self.score,
            "verdict": self.verdict,
            "critical_hit": self.critical_hit,
            "awb": self.awb,
            "delivery_partner": self.delivery_partner,
            "raw_text": self.raw_text,
            "barcodes": list(self.barcodes),
            "checks": [asdict(c) for c in self.checks],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #

def validate_label(path: str, *, dpi: int = 300, report_html_path: str | None = None) -> LabelResult:
    """Validate a single label PDF and return a :class:`LabelResult`.

    :param path: path to the label PDF.
    :param dpi: render DPI used for barcode decoding (higher = slower, more robust).
    :param report_html_path: if given, also write a visual HTML report there.
    """
    pdf = LabelPDF(path, render_dpi=dpi)
    try:
        results = run_all(pdf)
        text = pdf.full_text()
        barcodes = [b.value for b in pdf.barcodes()]
        report = Report(
            path=path,
            results=results,
            raw_text=text,
            barcodes=barcodes,
            awb=extract_awb(text, barcodes),
            delivery_partner=extract_delivery_partner(text),
        )
        if report_html_path:
            from .report_html import build_html_report
            build_html_report(pdf, report, report_html_path)
        return _from_report(report)
    finally:
        pdf.close()


def validate_labels(paths: Iterable[str], *, dpi: int = 300) -> list[LabelResult]:
    """Validate several label PDFs; returns one :class:`LabelResult` each."""
    return [validate_label(p, dpi=dpi) for p in paths]


# --------------------------------------------------------------------------- #
# Internal: adapt the implementation's Report into the public LabelResult
# --------------------------------------------------------------------------- #

def _from_report(report: Report) -> LabelResult:
    verdict, _ = report.verdict()
    checks = [
        CheckOutcome(
            key=r.key,
            title=r.title,
            status=r.status.value,
            penalty=r.penalty,
            summary=r.summary,
            findings=[
                Finding(
                    message=f.message,
                    where=f.where,
                    evidence=f.evidence,
                    critical=f.critical,
                    penalty=f.penalty,
                )
                for f in r.findings
            ],
        )
        for r in report.results
    ]
    return LabelResult(
        file=report.path,
        verdict=verdict,
        score=report.score(),
        critical_hit=any(r.has_critical_finding for r in report.results),
        awb=report.awb,
        delivery_partner=report.delivery_partner,
        raw_text=report.raw_text or "",
        barcodes=list(report.barcodes or []),
        checks=checks,
    )
