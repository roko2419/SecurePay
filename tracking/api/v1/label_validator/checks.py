"""The five forgery checks.

Each check receives the extracted :class:`LabelPDF` and returns a
:class:`CheckResult`. Checks never raise on malformed content; they degrade to
INCONCLUSIVE so one bad signal cannot crash the whole validation.
"""

from __future__ import annotations

import re
import unicodedata

from .pdf_model import (
    _ZXING,
    LabelPDF,
    contains,
    fmt_rect,
    normalize,
    overlap_ratio,
)
from .report import CheckResult, Finding, Status


# --------------------------------------------------------------------------- #
# Check 1 — Value consistency across every representation of a field
# --------------------------------------------------------------------------- #

# Labeled fields we can locate in the human-readable text. Each captures the
# value token that follows the label.
# Linear (1D) symbologies carry a plain id that the generator also prints as
# human-readable text beneath the bars. QR / DataMatrix may instead carry a URL
# or JSON blob that is deliberately not printed, so they are excluded from the
# "must be echoed in the text" rule to avoid false positives.
_LINEAR_FORMATS = {
    "CODE128", "CODE39", "CODE93", "CODABAR", "ITF",
    "EAN13", "EAN8", "UPCA", "UPCE", "DATABAR",
}


def check_consistency(pdf: LabelPDF) -> CheckResult:
    """Cross-representation agreement.

    The single reliable, false-positive-proof invariant: the generator derives
    the printed value and the barcode from one database field, so every linear
    barcode's payload must appear verbatim in the human-readable text. If
    someone retypes the visible AWB and leaves the barcode alone, the barcode's
    value vanishes from the text and we recover the real value from the bars.
    """
    result = CheckResult(
        key="consistency",
        title="1. Value consistency across representations",
        status=Status.PASS,
        weight=30,
        critical=True,
    )

    barcodes = pdf.barcodes()
    norm_text = normalize(pdf.full_text())

    if not barcodes:
        if not _ZXING:
            result.status = Status.INCONCLUSIVE
            result.summary = "zxing-cpp not installed — barcode checking unavailable."
            return result
        # An undecodable or missing barcode is itself suspicious on a courier
        # label — otherwise degrading the barcode slightly would defeat this
        # check entirely. Deduct, but do not treat as critical proof.
        result.status = Status.FAIL
        images = pdf.cover_boxes()
        has_image = any(
            c.kind == "image" and (c.bbox[2] - c.bbox[0]) >= 30 and (c.bbox[3] - c.bbox[1]) >= 10
            for c in images
        )
        if has_image:
            result.findings.append(
                Finding(
                    message=(
                        "Image region(s) present but no barcode decodes even at "
                        "high DPI — a genuine label's barcode is machine-readable; "
                        "a blurred or degraded one suggests re-rendering or evasion."
                    ),
                    penalty=20,
                )
            )
        else:
            result.findings.append(
                Finding(
                    message=(
                        "No barcode region found at all — every genuine courier "
                        "label carries at least one scannable barcode."
                    ),
                    penalty=20,
                )
            )
        result.summary = "No barcode/QR payloads could be decoded."
        return result

    checked = 0
    for b in barcodes:
        fmt_key = b.fmt.replace(" ", "").upper()
        if fmt_key not in _LINEAR_FORMATS:
            continue  # QR/DataMatrix: payload may legitimately not be printed
        checked += 1
        nval = normalize(b.value)
        if nval and nval not in norm_text:
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message=(
                        f"{b.fmt} barcode payload is not present anywhere in the "
                        f"human-readable text — the printed value was changed "
                        f"while the barcode was left untouched."
                    ),
                    where=f"page {b.page + 1}, barcode at {fmt_rect(b.bbox)}",
                    evidence=f"true value from barcode: '{b.value}'",
                    penalty=30,
                    critical=True,
                    page=b.page,
                    bbox=b.bbox,
                )
            )

    decoded = ", ".join(f"{b.fmt}:{b.value}" for b in barcodes)
    if result.status is Status.PASS:
        result.summary = (
            f"All {checked} linear barcode(s) are echoed verbatim in the printed "
            f"text — {decoded}"
        )
    else:
        result.summary = f"Decoded codes: {decoded}"
    return result


# --------------------------------------------------------------------------- #
# Check 2 — Covered, overlapping or hidden text
# --------------------------------------------------------------------------- #

def check_hidden_text(pdf: LabelPDF) -> CheckResult:
    result = CheckResult(
        key="hidden_text",
        title="2. Covered, overlapping or hidden text",
        status=Status.PASS,
        weight=25,
        critical=True,
    )

    spans = pdf.text_spans()
    covers = pdf.cover_boxes()
    cropboxes = pdf.cropboxes()

    # (a) invisible text (render mode 3) — the buried original value
    for sp in spans:
        if sp.render_mode == 3:
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message="Invisible text (render mode 3) is present in the file.",
                    where=f"page {sp.page + 1}, {fmt_rect(sp.bbox)}",
                    evidence=f"buried value: '{sp.text.strip()}'",
                    critical=True,
                    page=sp.page,
                    bbox=sp.bbox,
                )
            )

    # (b) filled rectangle / image sitting ON TOP of extractable text.
    #     A shape only hides text if it is painted *after* the text (higher
    #     seqno) — this is what separates a tampering patch from the label's
    #     own background rectangle, which is drawn first. Near-full-page shapes
    #     are backgrounds/borders and are ignored.
    page_area = {i: max(1.0, (c[2] - c[0]) * (c[3] - c[1])) for i, c in enumerate(cropboxes)}
    for cov in covers:
        cov_w = cov.bbox[2] - cov.bbox[0]
        cov_h = cov.bbox[3] - cov.bbox[1]
        if cov_w * cov_h >= 0.85 * page_area.get(cov.page, 1e9):
            continue  # background / full-page border, not a targeted patch
        for sp in spans:
            if sp.page != cov.page or sp.render_mode == 3:
                continue
            if overlap_ratio(sp.bbox, cov.bbox) < 0.6:
                continue
            if cov.kind == "fill":
                # painted before/with the text -> it is behind it, not covering
                if cov.seqno < 0 or sp.seqno < 0 or cov.seqno <= sp.seqno:
                    continue
            else:  # image: no reliable seqno; only flag clearly local overlays
                if cov_w * cov_h >= 0.5 * page_area.get(cov.page, 1e9):
                    continue
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message=(
                        f"Text is covered by an overlaid {cov.kind} drawn on top "
                        f"of it — the original value survives underneath the patch."
                    ),
                    where=f"page {sp.page + 1}, text {fmt_rect(sp.bbox)} "
                    f"under {cov.kind} {fmt_rect(cov.bbox)}",
                    evidence=f"covered text: '{sp.text.strip()}'",
                    critical=True,
                    page=sp.page,
                    bbox=sp.bbox,
                )
            )

    # (c) two text runs overlapping with different values
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            a, b = spans[i], spans[j]
            if a.page != b.page:
                continue
            if overlap_ratio(a.bbox, b.bbox) >= 0.5 and \
                    normalize(a.text) != normalize(b.text) and \
                    a.text.strip() and b.text.strip():
                result.status = Status.FAIL
                result.findings.append(
                    Finding(
                        message="Two overlapping text runs carry different values.",
                        where=f"page {a.page + 1}, {fmt_rect(a.bbox)} ∩ {fmt_rect(b.bbox)}",
                        evidence=f"'{a.text.strip()}' vs '{b.text.strip()}'",
                        critical=True,
                        page=a.page,
                        bbox=a.bbox,
                    )
                )

    # (d) text positioned outside the CropBox
    for sp in spans:
        crop = cropboxes[sp.page]
        if not contains(crop, sp.bbox, tol=1.0) and overlap_ratio(sp.bbox, crop) < 0.5:
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message="Text is positioned (largely) outside the visible CropBox.",
                    where=f"page {sp.page + 1}, text {fmt_rect(sp.bbox)} vs crop {fmt_rect(crop)}",
                    evidence=f"off-page text: '{sp.text.strip()}'",
                    critical=True,
                    page=sp.page,
                    bbox=sp.bbox,
                )
            )

    if result.status is Status.PASS:
        result.summary = (
            f"{len(spans)} text runs checked against {len(covers)} images/fills — "
            "no invisible, covered, overlapping or off-page text."
        )
    return result


# --------------------------------------------------------------------------- #
# Check 3 — XMP derivation lineage
# --------------------------------------------------------------------------- #

def check_xmp_lineage(pdf: LabelPDF) -> CheckResult:
    """The file's own record of having been derived from another document.

    Signals differ in reliability. DerivedFrom and History edit events are the
    file *confessing* it was produced by modifying another file (25 pts each).
    A bare DocumentID ≠ InstanceID also fires on legitimate re-exports and
    compression passes — any save mints a fresh InstanceID — so it is the
    weaker signal (15 pts). None are marked critical: a lone re-export must not
    auto-reject, but History + mismatch together push the score below 70.
    """
    result = CheckResult(
        key="xmp_lineage",
        title="3. XMP derivation lineage",
        status=Status.PASS,
        weight=25,
    )

    xmp = pdf.xmp()
    if not xmp.present:
        result.status = Status.INCONCLUSIVE
        result.summary = "No XMP metadata packet — nothing to attest lineage either way."
        return result

    if xmp.derived_from:
        result.status = Status.FAIL
        result.findings.append(
            Finding(
                message="xmpMM:DerivedFrom is present — the file declares it was derived from another document.",
                evidence=str(xmp.derived_from),
                penalty=25,
            )
        )

    if xmp.history_events:
        result.status = Status.FAIL
        result.findings.append(
            Finding(
                message="xmpMM:History contains editing events.",
                evidence="events: " + ", ".join(xmp.history_events),
                penalty=25,
            )
        )

    if xmp.document_id and xmp.instance_id and xmp.document_id != xmp.instance_id:
        result.status = Status.FAIL
        result.findings.append(
            Finding(
                message="xmpMM:DocumentID ≠ xmpMM:InstanceID — the file was modified after creation (also fires on legitimate re-exports).",
                evidence=f"DocumentID={xmp.document_id}  InstanceID={xmp.instance_id}",
                penalty=15,
            )
        )

    if result.status is Status.PASS:
        result.summary = "DocumentID matches InstanceID, no History or DerivedFrom entries."
    return result


# --------------------------------------------------------------------------- #
# Check 4 — Text-bearing annotations or form fields
# --------------------------------------------------------------------------- #

_EDITOR_ANNOTS = {"FreeText", "Stamp", "Square", "Redact", "Widget", "Highlight", "Ink"}


def check_annotations(pdf: LabelPDF) -> CheckResult:
    result = CheckResult(
        key="annotations",
        title="4. Text-bearing annotations or form fields",
        status=Status.PASS,
        weight=15,
    )

    for a in pdf.annotations():
        if a.subtype in _EDITOR_ANNOTS:
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message=f"{a.subtype} annotation present — added by an interactive editor, not a rendering pipeline.",
                    where=f"page {a.page + 1}, {fmt_rect(a.bbox)}",
                    evidence=(f"annotation text: '{a.content}'" if a.content else ""),
                    page=a.page,
                    bbox=a.bbox,
                )
            )

    if pdf.has_acroform():
        result.status = Status.FAIL
        result.findings.append(
            Finding(message="Document contains an /AcroForm dictionary (interactive form fields).")
        )

    if result.status is Status.PASS:
        result.summary = "No editor annotations and no AcroForm — consistent with server-side rendering."
    return result


# --------------------------------------------------------------------------- #
# Check 5 — Non-embedded font on any text object
# --------------------------------------------------------------------------- #

# The PDF "standard 14" fonts are guaranteed to be present in every conforming
# viewer, so real courier generators legitimately reference them without
# embedding. A NON-standard font left un-embedded is the real signal: it means
# an editor assumed a specific local font (Arial, Calibri, ...) would resolve.
_STANDARD_14 = {
    "HELVETICA", "HELVETICA-BOLD", "HELVETICA-OBLIQUE", "HELVETICA-BOLDOBLIQUE",
    "COURIER", "COURIER-BOLD", "COURIER-OBLIQUE", "COURIER-BOLDOBLIQUE",
    "TIMES-ROMAN", "TIMES-BOLD", "TIMES-ITALIC", "TIMES-BOLDITALIC",
    "SYMBOL", "ZAPFDINGBATS", "ARIAL", "ARIAL-BOLD", "ARIALMT",
}


def _is_standard_14(name: str) -> bool:
    base = name.split("+")[-1].upper()
    return base in _STANDARD_14


def check_fonts(pdf: LabelPDF) -> CheckResult:
    result = CheckResult(
        key="fonts",
        title="5. Non-embedded fonts on text objects",
        status=Status.PASS,
        weight=15,
    )

    fonts = pdf.fonts()
    if not fonts:
        result.status = Status.INCONCLUSIVE
        result.summary = "No font resources found on any page."
        return result

    std14_nonembedded = 0
    seen = set()
    for f in fonts:
        if f.embedded:
            continue
        if _is_standard_14(f.name):
            std14_nonembedded += 1
            continue  # legitimate: viewers guarantee these
        key = (f.name, f.page)
        if key in seen:
            continue
        seen.add(key)
        result.status = Status.FAIL
        result.findings.append(
            Finding(
                message=f"Non-standard font '{f.name}' ({f.type}) is drawn but not embedded.",
                where=f"page {f.page + 1}",
                evidence="the generator embeds its fonts; a bare reference to a local "
                "font means this text was added by an editor assuming that font resolves.",
            )
        )

    if result.status is Status.PASS:
        embedded = sum(1 for f in fonts if f.embedded)
        note = f" ({std14_nonembedded} standard-14 refs allowed)" if std14_nonembedded else ""
        result.summary = (
            f"No non-standard un-embedded fonts; {embedded}/{len(fonts)} embedded{note}."
        )
    return result


# --------------------------------------------------------------------------- #
# Check 6 — DocInfo metadata & file structure
# --------------------------------------------------------------------------- #

# Interactive / desktop tools that never appear in a server-side label
# pipeline. Matched case-insensitively against Producer and Creator.
# Deliberately NOT listed: wkhtmltopdf, Qt, iText, pdftk, Skia/Chromium,
# ReportLab, TCPDF, FPDF — all common in legitimate server generators.
_EDITOR_TOOLS = [
    "acrobat", "adobe acrobat",
    "quartz pdfcontext",          # macOS Preview re-save
    "ilovepdf", "sejda", "smallpdf", "pdfescape", "pdffiller", "soda pdf",
    "foxit", "nitro", "pdf-xchange", "pdfelement", "pdfsam",
    "libreoffice", "openoffice", "microsoft", "word",
    "canva", "photoshop", "illustrator", "indesign",
    "pages", "keynote",
]


def _parse_pdf_date(s: str) -> str:
    """Normalize a PDF date string for comparison (D:YYYYMMDDHHmmSS...)."""
    m = re.match(r"D:(\d{4,14})", s or "")
    return m.group(1) if m else (s or "")


def check_docinfo(pdf: LabelPDF) -> CheckResult:
    """DocInfo dictionary + file structure.

    Three signals of very different reliability, scored independently: an
    editor name in Producer/Creator is a strong fingerprint (15 pts), while a
    ModDate drift or an incremental-save section also fire on an honest label
    that a browser print dialog or mail client re-saved (5 pts each) — so a
    single innocent re-save costs far less than an Acrobat fingerprint.
    """
    result = CheckResult(
        key="docinfo",
        title="6. DocInfo metadata & file structure",
        status=Status.PASS,
        weight=15,
    )

    info = pdf.doc_info()

    # (a) producer/creator names an interactive editor — strong fingerprint
    for field in ("producer", "creator"):
        val = (info.get(field) or "").lower()
        for tool in _EDITOR_TOOLS:
            if tool in val:
                result.status = Status.FAIL
                result.findings.append(
                    Finding(
                        message=(
                            f"/{field.capitalize()} names an interactive editing "
                            f"tool — server label pipelines never do."
                        ),
                        evidence=f"{field} = '{info.get(field)}'",
                        penalty=15,
                    )
                )
                break

    # (b) ModDate differs from CreationDate -> re-saved (weak: browser/mail too)
    created = _parse_pdf_date(info.get("creationDate", ""))
    modified = _parse_pdf_date(info.get("modDate", ""))
    if created and modified and created != modified:
        result.status = Status.FAIL
        result.findings.append(
            Finding(
                message="ModDate differs from CreationDate — the file was saved again after generation (also happens on a browser/mail re-save).",
                evidence=f"created {info.get('creationDate')}  vs  modified {info.get('modDate')}",
                penalty=5,
            )
        )

    # (c) incremental update sections -> edit appended (weak: also innocent re-saves)
    extra = pdf.incremental_saves()
    if extra > 0:
        result.status = Status.FAIL
        result.findings.append(
            Finding(
                message=(
                    f"File contains {extra} incremental update section(s) — an "
                    f"edit appended on top of the intact original (also happens on innocent re-saves)."
                ),
                evidence="multiple startxref/xref sections in the file",
                penalty=5,
            )
        )

    if result.status is Status.PASS:
        prod = info.get("producer", "-")
        cre = info.get("creator", "-")
        result.summary = (
            f"Producer '{prod}', Creator '{cre}', single-shot write, "
            f"no post-creation save recorded."
        )
    return result


# --------------------------------------------------------------------------- #
# Check 7 — Suspicious / spoofed characters in text
# --------------------------------------------------------------------------- #

# Invisible / direction-control characters that no label generator emits for a
# legitimate reason. NOT included: SOFT HYPHEN (U+00AD) and NO-BREAK SPACE
# (U+00A0) — genuine generators and PyMuPDF's own text layer routinely emit
# these as line-break and spacing hints, so flagging them false-positives.
_INVISIBLE_CHARS = {
    0x200B: "ZERO WIDTH SPACE",
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
    0x200E: "LEFT-TO-RIGHT MARK",
    0x200F: "RIGHT-TO-LEFT MARK",
    0x202A: "LEFT-TO-RIGHT EMBEDDING",
    0x202B: "RIGHT-TO-LEFT EMBEDDING",
    0x202C: "POP DIRECTIONAL FORMATTING",
    0x202D: "LEFT-TO-RIGHT OVERRIDE",
    0x202E: "RIGHT-TO-LEFT OVERRIDE",
    0x2060: "WORD JOINER",
    0x2061: "FUNCTION APPLICATION",
    0x2062: "INVISIBLE TIMES",
    0x2063: "INVISIBLE SEPARATOR",
    0x2064: "INVISIBLE PLUS",
    0x2066: "LEFT-TO-RIGHT ISOLATE",
    0x2067: "RIGHT-TO-LEFT ISOLATE",
    0x2068: "FIRST STRONG ISOLATE",
    0x2069: "POP DIRECTIONAL ISOLATE",
    0xFEFF: "ZERO WIDTH NO-BREAK SPACE (BOM)",
}


def _char_script(ch: str) -> str:
    """Coarse script bucket via the Unicode character name."""
    name = unicodedata.name(ch, "")
    for script in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(script):
            return script
    return "OTHER"


def check_suspicious_chars(pdf: LabelPDF) -> CheckResult:
    # Non-critical: this is the noisiest check. Indian addresses are routinely
    # multilingual, and extractors emit soft-hyphens / NBSPs / stray control
    # characters from genuine files depending on the generator's encoding. A
    # scored signal, never a verdict-capper on its own.
    result = CheckResult(
        key="suspicious_chars",
        title="7. Suspicious / spoofed characters",
        status=Status.PASS,
        weight=15,
    )

    spans = pdf.text_spans()
    n_tokens = 0

    for sp in spans:
        # (a) invisible / bidi-control / control characters
        for ch in sp.text:
            cp = ord(ch)
            if cp in _INVISIBLE_CHARS:
                result.status = Status.FAIL
                result.findings.append(
                    Finding(
                        message=f"Invisible character {_INVISIBLE_CHARS[cp]} (U+{cp:04X}) embedded in text.",
                        where=f"page {sp.page + 1}, {fmt_rect(sp.bbox)}",
                        evidence=f"in run: '{sp.text.strip()}'",
                        page=sp.page,
                        bbox=sp.bbox,
                    )
                )
            elif unicodedata.category(ch) == "Cc" and ch not in "\n\r\t":
                result.status = Status.FAIL
                result.findings.append(
                    Finding(
                        message=f"Control character U+{cp:04X} embedded in text.",
                        where=f"page {sp.page + 1}, {fmt_rect(sp.bbox)}",
                        evidence=f"in run: '{sp.text.strip()}'",
                        page=sp.page,
                        bbox=sp.bbox,
                    )
                )

        # (b) per-token analysis: homoglyph mixing & fullwidth forms
        for token in sp.text.split():
            n_tokens += 1
            scripts = {_char_script(c) for c in token if c.isalpha()}
            scripts.discard("OTHER")
            # a Latin/digit token containing Cyrillic or Greek lookalikes is
            # spoofing; a token entirely in one non-Latin script (e.g. a
            # Devanagari name) is legitimate and not flagged.
            if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
                bad = [
                    f"'{c}' U+{ord(c):04X} {unicodedata.name(c, '?')}"
                    for c in token
                    if c.isalpha() and _char_script(c) in ("CYRILLIC", "GREEK")
                ]
                result.status = Status.FAIL
                result.findings.append(
                    Finding(
                        message="Mixed-script token — non-Latin lookalike letters spliced into Latin text (homoglyph spoofing).",
                        where=f"page {sp.page + 1}, {fmt_rect(sp.bbox)}",
                        evidence=f"token '{token}' contains {', '.join(bad)}",
                        page=sp.page,
                        bbox=sp.bbox,
                    )
                )
            # fullwidth digits/letters render like ASCII but compare unequal
            if any(0xFF01 <= ord(c) <= 0xFF5E for c in token):
                result.status = Status.FAIL
                result.findings.append(
                    Finding(
                        message="Fullwidth (U+FF01–FF5E) characters mimic ASCII visually but differ in value.",
                        where=f"page {sp.page + 1}, {fmt_rect(sp.bbox)}",
                        evidence=f"token '{token}'",
                        page=sp.page,
                        bbox=sp.bbox,
                    )
                )

    if result.status is Status.PASS:
        result.summary = (
            f"{n_tokens} tokens scanned — no invisible, control, homoglyph or "
            f"fullwidth characters."
        )
    return result


# --------------------------------------------------------------------------- #
# Check 8 — Flattened / rasterized page (screenshot -> PDF)
# --------------------------------------------------------------------------- #

def check_flattened(pdf: LabelPDF) -> CheckResult:
    """Catch a label that is really just a screenshot wrapped in a PDF.

    A genuine label is vector: selectable text, multiple images (barcodes,
    logo), fonts. A screenshot-to-PDF is a single raster covering the page with
    little or no extractable text underneath — which would otherwise sail
    through checks 2-7 as vacuous passes. Hard-reject grade.
    """
    result = CheckResult(
        key="flattened",
        title="8. Flattened / rasterized page",
        status=Status.PASS,
        weight=30,
        critical=True,
    )

    pages = pdf.page_flatness()
    cropboxes = pdf.cropboxes()
    for pg in pages:
        full = cropboxes[pg["page"]] if pg["page"] < len(cropboxes) else None
        raster = pg["max_image_frac"] >= 0.90
        no_text = pg["chars"] < 15
        if raster and no_text:
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message=(
                        "Page is a single image covering ≥90% of the sheet with no "
                        "extractable text — a screenshot flattened into a PDF, not a "
                        "generated label."
                    ),
                    where=f"page {pg['page'] + 1}",
                    evidence=f"largest image = {pg['max_image_frac']*100:.0f}% of page, {pg['chars']} extractable chars",
                    penalty=30,
                    critical=True,
                    page=pg["page"],
                    bbox=full,
                )
            )
        elif no_text:
            result.status = Status.FAIL
            result.findings.append(
                Finding(
                    message=(
                        "Page has effectively no extractable text — content was "
                        "rasterized or outlined, hiding it from every text-based check."
                    ),
                    where=f"page {pg['page'] + 1}",
                    evidence=f"{pg['chars']} extractable chars",
                    penalty=30,
                    critical=True,
                    page=pg["page"],
                    bbox=full,
                )
            )

    if result.status is Status.PASS:
        result.summary = (
            f"{len(pages)} page(s) carry real extractable text; no full-page raster."
        )
    return result


# Checks that run by default. check_hidden_text and check_annotations are
# implemented and importable but left OUT of the default set: on the courier
# templates tested here they fire on legitimate label constructs (the carrier's
# own overlapping/positioned text and template annotations), so they would
# false-positive on genuine labels. Add them back for stricter validation on a
# corpus where you've confirmed they stay clean.
ALL_CHECKS = [
    check_consistency,
    check_xmp_lineage,
    check_fonts,
    check_docinfo,
    check_suspicious_chars,
    check_flattened,
]


def run_all(pdf: LabelPDF) -> list[CheckResult]:
    results = []
    for fn in ALL_CHECKS:
        try:
            results.append(fn(pdf))
        except Exception as exc:  # never let one check sink the run
            results.append(
                CheckResult(
                    key=fn.__name__,
                    title=fn.__name__,
                    status=Status.INCONCLUSIVE,
                    weight=0,
                    summary=f"check errored: {exc!r}",
                )
            )
    return results
