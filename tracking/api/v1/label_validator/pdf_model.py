"""Shared PDF extraction layer.

Wraps a single courier-label PDF and exposes normalized primitives that the
five checks consume: decoded barcodes/QR codes, text spans (with render mode
and geometry), covering images / filled rectangles, font resources, XMP
metadata, annotations and the AcroForm flag.

Everything geometric is expressed in PDF points using PyMuPDF's top-left
origin convention so bounding boxes are directly comparable across sources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

import pymupdf

try:
    import zxingcpp
    from PIL import Image
    _ZXING = True
except Exception:  # pragma: no cover - optional at runtime
    _ZXING = False


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #

Rect = tuple[float, float, float, float]  # (x0, y0, x1, y1)


def _area(r: Rect) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def intersection(a: Rect, b: Rect) -> Rect:
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def overlap_ratio(a: Rect, b: Rect) -> float:
    """Intersection area divided by the smaller of the two areas.

    1.0 means one box fully contains the other; 0.0 means disjoint. Using the
    smaller area (rather than union/IoU) makes "text covered by a big
    rectangle" score highly, which is exactly what we want to flag.
    """
    inter = _area(intersection(a, b))
    if inter <= 0:
        return 0.0
    smaller = min(_area(a), _area(b))
    return inter / smaller if smaller > 0 else 0.0


def contains(outer: Rect, inner: Rect, tol: float = 1.0) -> bool:
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


def fmt_rect(r: Rect) -> str:
    return f"({r[0]:.0f},{r[1]:.0f})-({r[2]:.0f},{r[3]:.0f})"


# --------------------------------------------------------------------------- #
# Normalization used by the consistency check
# --------------------------------------------------------------------------- #

def normalize(value: str) -> str:
    """Collapse a field value to a comparable canonical form."""
    return re.sub(r"[\s\-_/.]", "", value).upper()


# --------------------------------------------------------------------------- #
# Extracted primitives
# --------------------------------------------------------------------------- #

@dataclass
class Barcode:
    value: str
    fmt: str            # e.g. "Code128", "QRCode"
    page: int
    bbox: Rect          # in PDF points


@dataclass
class TextSpan:
    text: str
    bbox: Rect
    page: int
    render_mode: int    # PDF text rendering mode; 3 == invisible
    font: str
    color: tuple
    seqno: int = -1     # paint order within the page's content stream


@dataclass
class CoverBox:
    kind: str           # "image" or "fill"
    bbox: Rect
    page: int
    seqno: int = -1     # paint order; a fill hides text only if drawn later


@dataclass
class FontRef:
    xref: int
    name: str           # base font name
    type: str           # Type1 / TrueType / Type0 ...
    embedded: bool
    page: int


@dataclass
class Annotation:
    subtype: str        # FreeText / Stamp / Square / Redact / Widget ...
    bbox: Rect
    page: int
    content: str


@dataclass
class XmpInfo:
    present: bool
    document_id: Optional[str] = None
    instance_id: Optional[str] = None
    original_document_id: Optional[str] = None
    derived_from: Optional[str] = None
    history_events: list[str] = field(default_factory=list)
    raw: str = ""


# --------------------------------------------------------------------------- #
# The document wrapper
# --------------------------------------------------------------------------- #

class LabelPDF:
    def __init__(self, path: str, render_dpi: int = 300):
        self.path = path
        self.render_dpi = render_dpi
        self.doc = pymupdf.open(path)

    def close(self) -> None:
        self.doc.close()

    # -- barcodes / QR ----------------------------------------------------- #
    def barcodes(self) -> list[Barcode]:
        """Decode every barcode/QR on every page.

        Shiprocket embeds each barcode as its own small image, which a
        whole-page scan often misses. We therefore decode each embedded image
        directly (most reliable) and additionally scan the full page render as
        a fallback for vector-drawn or large QR codes. Results are de-duplicated
        by normalized value, keeping the first known location.
        """
        if not _ZXING:
            return []
        import io

        found: dict[str, Barcode] = {}

        def add(value: str, fmt: str, page: int, bbox: Rect) -> None:
            if not value:
                return
            key = normalize(value)
            if key not in found:
                found[key] = Barcode(value, fmt, page, bbox)

        for pno, page in enumerate(self.doc):
            # (1) decode each embedded image directly
            for info in page.get_image_info(xrefs=True):
                xref = info.get("xref", 0)
                if xref <= 0:
                    continue
                try:
                    raw = self.doc.extract_image(xref)
                    img = Image.open(io.BytesIO(raw["image"])).convert("L")
                except Exception:
                    continue
                if min(img.size) < 8:
                    continue
                for res in zxingcpp.read_barcodes(img):
                    add(res.text, str(res.format), pno, tuple(info.get("bbox", (0, 0, 0, 0))))

            # (2) full-page render fallback (vector barcodes, big QR codes)
            scale = 72.0 / self.render_dpi
            pix = page.get_pixmap(dpi=self.render_dpi)
            mode = "RGB" if pix.n < 4 else "RGBA"
            pimg = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            if mode == "RGBA":
                pimg = pimg.convert("RGB")
            for res in zxingcpp.read_barcodes(pimg):
                if not res.text:
                    continue
                pos = res.position
                xs = [pos.top_left.x, pos.top_right.x, pos.bottom_left.x, pos.bottom_right.x]
                ys = [pos.top_left.y, pos.top_right.y, pos.bottom_left.y, pos.bottom_right.y]
                bbox = (min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale)
                add(res.text, str(res.format), pno, bbox)

        return list(found.values())

    # -- text spans (with render mode via texttrace) ----------------------- #
    def text_spans(self) -> list[TextSpan]:
        spans: list[TextSpan] = []
        for pno, page in enumerate(self.doc):
            for sp in page.get_texttrace():
                chars = sp.get("chars") or []
                text = "".join(chr(c[0]) for c in chars if c[0])
                if not text.strip():
                    continue
                spans.append(
                    TextSpan(
                        text=text,
                        bbox=tuple(sp["bbox"]),
                        page=pno,
                        render_mode=int(sp.get("type", 0)),
                        font=sp.get("font", ""),
                        color=tuple(sp.get("color") or ()),
                        seqno=int(sp.get("seqno", -1)),
                    )
                )
        return spans

    def full_text(self) -> str:
        return "\n".join(page.get_text("text") for page in self.doc)

    # -- covering images and filled rectangles ----------------------------- #
    def cover_boxes(self) -> list[CoverBox]:
        boxes: list[CoverBox] = []
        for pno, page in enumerate(self.doc):
            for info in page.get_image_info(xrefs=True):
                bbox = info.get("bbox")
                if bbox:
                    boxes.append(CoverBox("image", tuple(bbox), pno, seqno=-1))
            try:
                drawings = page.get_drawings()
            except Exception:
                drawings = []
            for d in drawings:
                if d.get("fill") is None:  # only opaque filled shapes hide text
                    continue
                r = d.get("rect")
                if r is not None:
                    boxes.append(CoverBox("fill", tuple(r), pno, seqno=int(d.get("seqno", -1))))
        return boxes

    def cropboxes(self) -> list[Rect]:
        return [tuple(page.cropbox) for page in self.doc]

    # -- fonts ------------------------------------------------------------- #
    def fonts(self) -> list[FontRef]:
        refs: list[FontRef] = []
        for pno, page in enumerate(self.doc):
            for f in page.get_fonts(full=True):
                xref, ext, ftype, basefont = f[0], f[1], f[2], f[3]
                refs.append(
                    FontRef(
                        xref=xref,
                        name=basefont,
                        type=ftype,
                        embedded=(ext not in ("n/a", "", None)),
                        page=pno,
                    )
                )
        return refs

    # -- XMP metadata ------------------------------------------------------ #
    def xmp(self) -> XmpInfo:
        raw = self.doc.get_xml_metadata() or ""
        if not raw.strip():
            return XmpInfo(present=False)

        def grab(attr: str) -> Optional[str]:
            m = re.search(rf"{attr}\s*=\s*[\"']([^\"']*)[\"']", raw)
            if m:
                return m.group(1)
            m = re.search(rf"<{attr}>(.*?)</{attr}>", raw, re.S)
            return m.group(1).strip() if m else None

        events: list[str] = []
        for evt in re.findall(r"<rdf:li[^>]*stEvt:action[^>]*>", raw) or []:
            m = re.search(r'stEvt:action\s*=\s*["\']([^"\']*)["\']', evt)
            if m:
                events.append(m.group(1))
        # stEvt often appears as nested elements too
        events += re.findall(r"<stEvt:action>(.*?)</stEvt:action>", raw, re.S)

        return XmpInfo(
            present=True,
            document_id=grab("xmpMM:DocumentID"),
            instance_id=grab("xmpMM:InstanceID"),
            original_document_id=grab("xmpMM:OriginalDocumentID"),
            derived_from=grab("xmpMM:DerivedFrom") or (
                "present" if "DerivedFrom" in raw else None
            ),
            history_events=[e.strip() for e in events if e.strip()],
            raw=raw,
        )

    # -- DocInfo dictionary & file structure -------------------------------- #
    def doc_info(self) -> dict[str, str]:
        """The classic /Info dictionary (Producer, Creator, dates, ...)."""
        return {k: v for k, v in (self.doc.metadata or {}).items() if v}

    def incremental_saves(self) -> int:
        """Number of xref sections beyond the first.

        A PDF written in one shot has exactly one ``startxref``. Every
        incremental save (Preview, Acrobat "Save", many editors) appends a new
        body + xref section, leaving the original document intact underneath.
        """
        try:
            with open(self.path, "rb") as fh:
                data = fh.read()
        except OSError:
            return 0
        return max(0, data.count(b"startxref") - 1)

    # -- flattening / screenshot detection --------------------------------- #
    def page_flatness(self) -> list[dict]:
        """Per-page structure summary used to spot a rasterized/flattened page.

        Returns one dict per page with the number of extractable characters and
        the fraction of the page covered by its single largest image. A genuine
        vector label has plenty of real text; a screenshot-turned-PDF is one big
        image with little or no text underneath.
        """
        out: list[dict] = []
        for pno, page in enumerate(self.doc):
            crop = page.cropbox
            page_area = max(1.0, crop.width * crop.height)
            chars = len(page.get_text("text").strip())
            biggest = 0.0
            for info in page.get_image_info(xrefs=True):
                b = info.get("bbox")
                if not b:
                    continue
                a = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
                biggest = max(biggest, a / page_area)
            out.append({"page": pno, "chars": chars, "max_image_frac": biggest})
        return out

    # -- annotations & AcroForm ------------------------------------------- #
    def annotations(self) -> list[Annotation]:
        out: list[Annotation] = []
        for pno, page in enumerate(self.doc):
            for a in page.annots() or []:
                subtype = a.type[1] if isinstance(a.type, (list, tuple)) else str(a.type)
                out.append(
                    Annotation(
                        subtype=subtype,
                        bbox=tuple(a.rect),
                        page=pno,
                        content=(a.info or {}).get("content", "") or "",
                    )
                )
        return out

    def has_acroform(self) -> bool:
        try:
            cat = self.doc.pdf_catalog()
            kind, _ = self.doc.xref_get_key(cat, "AcroForm")
            return kind not in ("null", "unknown", None)
        except Exception:
            return False
