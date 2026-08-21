"""Result types, scoring and terminal rendering."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"  # check could not run (e.g. no barcode decoded)


@dataclass
class Finding:
    message: str            # what was wrong
    where: str = ""         # page / bbox / field locator (human-readable)
    evidence: str = ""      # the recovered value, buried string, etc.
    penalty: int | None = None  # per-finding deduction; None -> check weight applies
    critical: bool = False  # this specific finding caps the verdict at FORGED
    page: int | None = None      # 0-based page for the visual report, if known
    bbox: tuple | None = None    # (x0,y0,x1,y1) in PDF points, for the overlay box


@dataclass
class CheckResult:
    key: str
    title: str
    status: Status
    weight: int             # default penalty applied to the score on FAIL
    critical: bool = False  # check *can* produce verdict-capping findings
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)

    @property
    def penalty(self) -> int:
        """Deduction this check contributes to the 100-pt score.

        If any finding carries an explicit per-finding penalty, the check's
        deduction is the sum of those (signals of different reliability inside
        one check fire independently). Otherwise a FAIL costs the flat weight.
        """
        if self.status is not Status.FAIL:
            return 0
        explicit = [f.penalty for f in self.findings if f.penalty is not None]
        if explicit:
            return sum(explicit)
        return self.weight

    @property
    def has_critical_finding(self) -> bool:
        return self.status is Status.FAIL and any(f.critical for f in self.findings)


# --------------------------------------------------------------------------- #
# ANSI helpers (auto-disabled when not a TTY)
# --------------------------------------------------------------------------- #

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


BOLD = lambda t: _c("1", t)
GREEN = lambda t: _c("32", t)
RED = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
DIM = lambda t: _c("2", t)
CYAN = lambda t: _c("36", t)


_STATUS_TAG = {
    Status.PASS: lambda: GREEN(" PASS "),
    Status.FAIL: lambda: RED(" FAIL "),
    Status.INCONCLUSIVE: lambda: YELLOW(" N/A  "),
}


def _bar(score: int, width: int = 30) -> str:
    filled = round(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    color = GREEN if score >= 90 else (YELLOW if score >= 70 else RED)
    return color(bar)


@dataclass
class Report:
    path: str
    results: list[CheckResult]
    raw_text: str | None = None          # full extracted text of the label
    barcodes: list[str] | None = None    # decoded barcode/QR payloads
    awb: str | None = None               # tracking number (barcode/label)
    delivery_partner: str | None = None  # carrier whose label this is

    def score(self) -> int:
        penalty = sum(r.penalty for r in self.results)
        return max(0, 100 - penalty)

    def verdict(self) -> tuple[str, str]:
        """Return (label, color-name)."""
        score = self.score()
        critical_fail = any(r.has_critical_finding for r in self.results)
        if critical_fail or score < 70:
            return "LIKELY FORGED", "red"
        if score < 90:
            return "SUSPICIOUS", "yellow"
        return "LIKELY AUTHENTIC", "green"


# --------------------------------------------------------------------------- #
# Terminal rendering — operates on a public LabelResult (duck-typed, so this
# module does not import the api layer). Used by the CLI.
# --------------------------------------------------------------------------- #

_STATUS_TAG_STR = {
    "PASS": lambda: GREEN(" PASS "),
    "FAIL": lambda: RED(" FAIL "),
    "INCONCLUSIVE": lambda: YELLOW(" N/A  "),
}
_VERDICT_FN = {"LIKELY AUTHENTIC": GREEN, "SUSPICIOUS": YELLOW, "LIKELY FORGED": RED}


def render_terminal(result) -> str:
    """Coloured terminal report for a :class:`label_validator.api.LabelResult`."""
    lines: list[str] = ["", BOLD("═" * 62), BOLD("  COURIER LABEL VALIDATION"),
                        DIM(f"  {result.file}"), BOLD("═" * 62)]

    if result.awb or result.delivery_partner or result.barcodes:
        lines.append("")
        lines.append(BOLD("  Label identity"))
        lines.append(f"    {'AWB:':<18}{CYAN(result.awb) if result.awb else DIM('—')}")
        lines.append(f"    {'Delivery partner:':<18}"
                     f"{CYAN(result.delivery_partner) if result.delivery_partner else DIM('—')}")
        if result.barcodes:
            lines.append(f"    {'Barcodes:':<18}{DIM(', '.join(result.barcodes))}")

    for r in result.checks:
        lines.append("")
        lines.append(f"[{_STATUS_TAG_STR[r.status]()}] {BOLD(r.title)}")
        if r.summary:
            lines.append(f"        {DIM(r.summary)}")
        for f in r.findings:
            tags = ""
            if f.penalty is not None:
                tags += DIM(f" (−{f.penalty} pts)")
            if f.critical:
                tags += RED(" [critical]")
            lines.append(f"        {RED('•')} {f.message}{tags}")
            if f.where:
                lines.append(f"            {DIM('location:')} {f.where}")
            if f.evidence:
                lines.append(f"            {DIM('evidence:')} {CYAN(f.evidence)}")

    n_pass = sum(1 for r in result.checks if r.status == "PASS")
    n_fail = sum(1 for r in result.checks if r.status == "FAIL")
    n_na = sum(1 for r in result.checks if r.status == "INCONCLUSIVE")
    lines.append("")
    lines.append(BOLD("─" * 62))
    lines.append(f"  Checks: {GREEN(str(n_pass) + ' passed')}, "
                 f"{RED(str(n_fail) + ' failed')}, {YELLOW(str(n_na) + ' inconclusive')}")
    lines.append(f"  Authenticity score: {BOLD(str(result.score) + '/100')}  {_bar(result.score)}")
    lines.append(f"  Verdict: {_VERDICT_FN[result.verdict](BOLD(result.verdict))}")
    lines.append(BOLD("═" * 62))
    lines.append("")
    return "\n".join(lines)
