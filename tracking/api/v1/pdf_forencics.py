#!/usr/bin/env python3

import argparse
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF
import pikepdf
from fontTools.ttLib import TTFont


# ============================================================
# Helpers
# ============================================================

INDIRECT_RE = re.compile(r"(\d+)\s+(\d+)\s+R")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(data) -> str:
    raw = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()


def parse_ref(value):
    """
    Parse something like:
        '123 0 R'
    into:
        (123, 0)
    """
    if value is None:
        return None

    match = INDIRECT_RE.search(str(value))

    if not match:
        return None

    return int(match.group(1)), int(match.group(2))


def safe_str(value):
    try:
        return str(value)
    except Exception:
        return repr(value)


def pdf_obj_type(obj):
    try:
        if isinstance(obj, pikepdf.Dictionary):
            return "Dictionary"
        if isinstance(obj, pikepdf.Array):
            return "Array"
        if isinstance(obj, pikepdf.Stream):
            return "Stream"
    except Exception:
        pass

    return type(obj).__name__


# ============================================================
# Document metadata
# ============================================================

def extract_metadata(doc):
    metadata = dict(doc.metadata or {})

    return {
        "metadata": metadata,
        "page_count": len(doc),
        "pdf_version": getattr(doc, "pdf_version", None),
        "is_encrypted": doc.is_encrypted,
    }


# ============================================================
# PDF XREF / OBJECT STRUCTURE
# ============================================================

def extract_xref_structure(doc):
    total = doc.xref_length()

    objects = []
    type_counts = Counter()

    for xref in range(1, total):
        try:
            keys = doc.xref_get_keys(xref)

            if not keys:
                continue

            obj = {
                "xref": xref,
                "keys": list(keys),
            }

            # Useful top-level PDF object types
            for key in [
                "Type",
                "Subtype",
                "Length",
                "Filter",
                "Font",
                "Resources",
                "BBox",
            ]:
                try:
                    value = doc.xref_get_key(xref, key)

                    if value and value[0] != "null":
                        obj[key] = value[1]
                except Exception:
                    pass

            object_type = obj.get("Type", obj.get("Subtype"))

            if object_type:
                type_counts[str(object_type)] += 1

            objects.append(obj)

        except Exception:
            continue

    return {
        "xref_length": total,
        "object_count": len(objects),
        "type_counts": dict(type_counts),
        "objects": objects,
    }


# ============================================================
# STRUCTURE TREE
# ============================================================

class StructureAnalyzer:

    def __init__(self):
        self.node_count = 0
        self.max_depth = 0

        self.types = Counter()
        self.structure_roles = Counter()

        self.tables = 0
        self.rows = 0
        self.cells = 0
        self.figures = 0
        self.nonstruct = 0

        self.node_paths = []

    def visit(self, obj, depth=0, path=None, visited=None):
        if path is None:
            path = []

        if visited is None:
            visited = set()

        # Avoid cycles
        try:
            obj_id = id(obj)

            if obj_id in visited:
                return

            visited.add(obj_id)
        except Exception:
            pass

        if isinstance(obj, pikepdf.Dictionary):

            self.node_count += 1
            self.max_depth = max(self.max_depth, depth)

            node_type = None
            role = None

            try:
                if "/Type" in obj:
                    node_type = safe_str(obj["/Type"])

                if "/S" in obj:
                    role = safe_str(obj["/S"])
            except Exception:
                pass

            if node_type:
                self.types[node_type] += 1

            if role:
                self.structure_roles[role] += 1

                role_clean = role.lstrip("/")

                if role_clean == "Table":
                    self.tables += 1
                elif role_clean == "TR":
                    self.rows += 1
                elif role_clean in ("TD", "TH"):
                    self.cells += 1
                elif role_clean == "Figure":
                    self.figures += 1
                elif role_clean == "NonStruct":
                    self.nonstruct += 1

            self.node_paths.append({
                "depth": depth,
                "type": node_type,
                "role": role,
                "path": path,
            })

            # Walk every dictionary value.
            try:
                for key, value in obj.items():

                    # /Pg, /P etc. aren't normally structural children.
                    # But /K is the important child relationship.
                    if str(key) in ("/K", "/Kids", "/KIDS"):
                        self.visit(
                            value,
                            depth + 1,
                            path + [safe_str(key)],
                            visited,
                        )

            except Exception:
                pass

        elif isinstance(obj, pikepdf.Array):

            for index, item in enumerate(obj):
                self.visit(
                    item,
                    depth,
                    path + [f"[{index}]"],
                    visited,
                )


def extract_structure_tree(pdf):
    result = {
        "present": False,
        "root": None,
        "node_count": 0,
        "max_depth": 0,
        "tables": 0,
        "rows": 0,
        "cells": 0,
        "figures": 0,
        "nonstruct": 0,
        "roles": {},
        "types": {},
        "nodes": [],
    }

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return result

        root = pdf.Root["/StructTreeRoot"]

        analyzer = StructureAnalyzer()

        analyzer.visit(
            root,
            depth=0,
            path=["/StructTreeRoot"],
        )

        result.update({
            "present": True,
            "root": "/StructTreeRoot",
            "node_count": analyzer.node_count,
            "max_depth": analyzer.max_depth,
            "tables": analyzer.tables,
            "rows": analyzer.rows,
            "cells": analyzer.cells,
            "figures": analyzer.figures,
            "nonstruct": analyzer.nonstruct,
            "roles": dict(analyzer.structure_roles),
            "types": dict(analyzer.types),
            "nodes": analyzer.node_paths,
        })

    except Exception as exc:
        result["error"] = repr(exc)

    return result


# ============================================================
# FONT ANALYSIS
# ============================================================

def get_xref_from_ref(value):
    if isinstance(value, int):
        return value

    ref = parse_ref(value)

    if ref:
        return ref[0]

    return None


def inspect_embedded_font(font_bytes):
    """
    Try to understand an embedded TrueType/OpenType font.
    """
    result = {
        "success": False,
        "format": None,
        "glyph_count": None,
        "glyph_order": [],
        "cmap_count": None,
        "cmap": {},
    }

    try:
        font = TTFont(io.BytesIO(font_bytes), lazy=False)

        result["success"] = True
        result["format"] = font.flavor or "TTF/OTF"

        glyph_order = font.getGlyphOrder()

        result["glyph_count"] = len(glyph_order)
        result["glyph_order"] = [
            {
                "glyph_id": i,
                "glyph_name": name,
            }
            for i, name in enumerate(glyph_order)
        ]

        cmap = font.getBestCmap() or {}

        result["cmap_count"] = len(cmap)

        # Don't create a gigantic report for huge fonts.
        for codepoint, glyph_name in list(cmap.items())[:5000]:
            result["cmap"][f"U+{codepoint:04X}"] = {
                "character": chr(codepoint),
                "glyph_name": glyph_name,
            }

        font.close()

    except Exception as exc:
        result["error"] = repr(exc)

    return result


def extract_fonts(doc, pdf):
    fonts = []

    seen = set()

    for page_number, page in enumerate(doc, start=1):

        try:
            page_fonts = page.get_fonts(full=True)
        except Exception:
            continue

        for font in page_fonts:

            xref = font[0]

            if xref in seen:
                continue

            seen.add(xref)

            record = {
                "xref": xref,
                "page_first_seen": page_number,
                "raw": list(font),
            }

            # PyMuPDF font information
            if len(font) > 2:
                record["font_type"] = font[1]

            if len(font) > 3:
                record["name"] = font[3]

            if len(font) > 4:
                record["encoding"] = font[4]

            if len(font) > 5:
                record["embedded_info"] = font[5]

            # ------------------------------------------------
            # Inspect raw PDF font dictionary
            # ------------------------------------------------

            try:
                keys = doc.xref_get_keys(xref)

                record["pdf_keys"] = list(keys)

                for key in [
                    "Type",
                    "Subtype",
                    "BaseFont",
                    "Encoding",
                    "ToUnicode",
                    "DescendantFonts",
                    "FontDescriptor",
                    "Widths",
                    "FirstChar",
                    "LastChar",
                ]:
                    try:
                        value = doc.xref_get_key(xref, key)

                        if value and value[0] != "null":
                            record[key] = value[1]

                    except Exception:
                        pass

            except Exception:
                pass

            # ------------------------------------------------
            # ToUnicode
            # ------------------------------------------------

            try:
                if "ToUnicode" in record:

                    to_unicode_xref = get_xref_from_ref(
                        record["ToUnicode"]
                    )

                    if to_unicode_xref:
                        record["to_unicode_xref"] = to_unicode_xref

                        cmap_bytes = doc.xref_stream(
                            to_unicode_xref
                        )

                        record["to_unicode_sha256"] = (
                            sha256_bytes(cmap_bytes)
                        )

                        try:
                            record["to_unicode_preview"] = (
                                cmap_bytes.decode(
                                    "latin-1",
                                    errors="replace"
                                )[:10000]
                            )
                        except Exception:
                            pass

            except Exception as exc:
                record["to_unicode_error"] = repr(exc)

            # ------------------------------------------------
            # Font descriptor
            # ------------------------------------------------

            try:
                if "FontDescriptor" in record:

                    descriptor_xref = get_xref_from_ref(
                        record["FontDescriptor"]
                    )

                    if descriptor_xref:

                        record["font_descriptor_xref"] = (
                            descriptor_xref
                        )

                        descriptor_keys = doc.xref_get_keys(
                            descriptor_xref
                        )

                        record["font_descriptor_keys"] = list(
                            descriptor_keys
                        )

                        # FontFile / FontFile2 / FontFile3
                        for ff_key in [
                            "FontFile",
                            "FontFile2",
                            "FontFile3",
                        ]:

                            try:
                                value = doc.xref_get_key(
                                    descriptor_xref,
                                    ff_key
                                )

                                if not value or value[0] == "null":
                                    continue

                                ff_xref = get_xref_from_ref(
                                    value[1]
                                )

                                if not ff_xref:
                                    continue

                                font_bytes = doc.xref_stream(
                                    ff_xref
                                )

                                record["embedded_font"] = {
                                    "xref": ff_xref,
                                    "key": ff_key,
                                    "size": len(font_bytes),
                                    "sha256": sha256_bytes(
                                        font_bytes
                                    ),
                                }

                                # Try fontTools
                                record["glyph_font_analysis"] = (
                                    inspect_embedded_font(
                                        font_bytes
                                    )
                                )

                                break

                            except Exception:
                                continue

            except Exception as exc:
                record["font_descriptor_error"] = repr(exc)

            fonts.append(record)

    return fonts


# ============================================================
# GLYPH / CHARACTER USAGE
# ============================================================

def extract_glyph_usage(doc):
    pages = []

    total_chars = 0
    fonts_used = Counter()
    characters = Counter()

    for page_number, page in enumerate(doc, start=1):

        page_result = {
            "page": page_number,
            "spans": [],
        }

        try:
            raw = page.get_text("rawdict")
        except Exception as exc:
            page_result["error"] = repr(exc)
            pages.append(page_result)
            continue

        for block in raw.get("blocks", []):

            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):

                for span in line.get("spans", []):

                    font_name = span.get("font")

                    fonts_used[font_name] += 1

                    span_result = {
                        "font": font_name,
                        "size": span.get("size"),
                        "flags": span.get("flags"),
                        "color": span.get("color"),
                        "origin": span.get("origin"),
                        "bbox": span.get("bbox"),
                        "chars": [],
                    }

                    for char in span.get("chars", []):

                        c = char.get("c")

                        characters[c] += 1
                        total_chars += 1

                        span_result["chars"].append({
                            "char": c,
                            "origin": char.get("origin"),
                            "bbox": char.get("bbox"),
                        })

                    page_result["spans"].append(span_result)

        pages.append(page_result)

    return {
        "total_characters": total_chars,
        "font_span_counts": dict(fonts_used),
        "character_frequency": dict(characters),
        "pages": pages,
    }


# ============================================================
# CONTENT STREAM ANALYSIS
# ============================================================

CONTENT_OPERATORS = [
    "Tj",
    "TJ",
    "Tf",
    "Tm",
    "Td",
    "TD",
    "T*",
    "Tc",
    "Tw",
    "Tz",
    "TL",
    "Ts",
    "Tr",
    "BT",
    "ET",
    "Do",
    "q",
    "Q",
]


def extract_content_streams(doc):
    result = {
        "operator_counts": Counter(),
        "pages": [],
    }

    for page_number, page in enumerate(doc, start=1):

        page_result = {
            "page": page_number,
            "stream_count": 0,
            "stream_sha256": [],
            "operator_counts": {},
        }

        try:
            contents = page.get_contents()
        except Exception:
            contents = []

        if not contents:
            contents = []

        page_result["stream_count"] = len(contents)

        page_counter = Counter()

        for xref in contents:

            try:
                stream = doc.xref_stream(xref)

                page_result["stream_sha256"].append({
                    "xref": xref,
                    "size": len(stream),
                    "sha256": sha256_bytes(stream),
                })

                text = stream.decode(
                    "latin-1",
                    errors="replace"
                )

                for operator in CONTENT_OPERATORS:

                    # Basic operator counting.
                    matches = re.findall(
                        rf"(?<![A-Za-z]){re.escape(operator)}(?![A-Za-z])",
                        text,
                    )

                    page_counter[operator] += len(matches)

            except Exception:
                continue

        page_result["operator_counts"] = dict(page_counter)

        result["pages"].append(page_result)

        result["operator_counts"].update(page_counter)

    result["operator_counts"] = dict(
        result["operator_counts"]
    )

    return result


# ============================================================
# IMAGES
# ============================================================

def extract_images(doc):
    images = []

    for page_number, page in enumerate(doc, start=1):

        try:
            page_images = page.get_images(full=True)
        except Exception:
            continue

        for image in page_images:

            xref = image[0]

            record = {
                "page": page_number,
                "xref": xref,
                "width": image[2],
                "height": image[3],
                "colorspace": image[5] if len(image) > 5 else None,
                "name": image[7] if len(image) > 7 else None,
            }

            try:
                data = doc.extract_image(xref)

                image_bytes = data["image"]

                record["format"] = data.get("ext")
                record["size"] = len(image_bytes)
                record["sha256"] = sha256_bytes(
                    image_bytes
                )

            except Exception:
                pass

            images.append(record)

    return images


# ============================================================
# PAGE GEOMETRY
# ============================================================

def extract_pages(doc):
    pages = []

    for page_number, page in enumerate(doc, start=1):

        rect = page.rect

        pages.append({
            "page": page_number,
            "width": rect.width,
            "height": rect.height,
            "rotation": page.rotation,
            "mediabox": list(page.mediabox),
            "cropbox": list(page.cropbox),
        })

    return pages


# ============================================================
# STRUCTURAL FINGERPRINT
# ============================================================

def make_structural_fingerprint(
    structure,
    fonts,
    content,
    images,
    pages,
):
    """
    Deliberately excludes variable information such as:
      - actual text
      - addresses
      - AWB
      - timestamps
      - metadata

    This is intended to represent the document's
    construction pattern.
    """

    font_features = []

    for font in fonts:

        embedded = font.get("embedded_font") or {}

        glyph_analysis = font.get(
            "glyph_font_analysis"
        ) or {}

        font_features.append({
            "font_type": font.get("font_type"),
            "encoding": font.get("encoding"),
            "has_tounicode": "ToUnicode" in font,
            "embedded": bool(embedded),
            "embedded_size": embedded.get("size"),
            "embedded_sha256": embedded.get("sha256"),
            "glyph_count": glyph_analysis.get(
                "glyph_count"
            ),
        })

    fingerprint_source = {
        "page_count": len(pages),

        "structure": {
            "present": structure.get("present"),
            "node_count": structure.get("node_count"),
            "max_depth": structure.get("max_depth"),
            "tables": structure.get("tables"),
            "rows": structure.get("rows"),
            "cells": structure.get("cells"),
            "figures": structure.get("figures"),
            "nonstruct": structure.get("nonstruct"),
            "roles": structure.get("roles"),
            "types": structure.get("types"),
        },

        "fonts": sorted(
            font_features,
            key=lambda x: json.dumps(
                x,
                sort_keys=True
            ),
        ),

        "content_operators": content.get(
            "operator_counts",
            {},
        ),

        "image_count": len(images),

        "page_geometry": [
            {
                "width": round(p["width"], 3),
                "height": round(p["height"], 3),
                "rotation": p["rotation"],
            }
            for p in pages
        ],
    }

    return {
        "algorithm": "sha256",
        "source": fingerprint_source,
        "sha256": sha256_json(
            fingerprint_source
        ),
    }


# ============================================================
# MAIN FORENSIC ANALYSIS
# ============================================================

def analyze_pdf(pdf_path):
    pdf_path = Path(pdf_path)

    print(f"[+] Opening {pdf_path}")

    doc = fitz.open(pdf_path)
    pdf = pikepdf.Pdf.open(pdf_path)

    print("[+] Extracting metadata...")
    metadata = extract_metadata(doc)

    print("[+] Extracting XRef/object structure...")
    xref_structure = extract_xref_structure(doc)

    print("[+] Extracting structure tree...")
    structure = extract_structure_tree(pdf)

    print("[+] Extracting fonts...")
    fonts = extract_fonts(doc, pdf)

    print("[+] Extracting glyph usage...")
    glyph_usage = extract_glyph_usage(doc)

    print("[+] Extracting content streams...")
    content = extract_content_streams(doc)

    print("[+] Extracting images...")
    images = extract_images(doc)

    print("[+] Extracting page geometry...")
    pages = extract_pages(doc)

    print("[+] Building structural fingerprint...")

    fingerprint = make_structural_fingerprint(
        structure,
        fonts,
        content,
        images,
        pages,
    )

    report = {
        "tool": {
            "name": "PDF Forensic Analyzer",
            "version": "1.0",
        },

        "file": {
            "path": str(pdf_path),
            "size": pdf_path.stat().st_size,
            "sha256": sha256_bytes(
                pdf_path.read_bytes()
            ),
        },

        "metadata": metadata,

        "xref_structure": xref_structure,

        "structure_tree": structure,

        "fonts": fonts,

        "glyph_usage": glyph_usage,

        "content_streams": content,

        "images": images,

        "pages": pages,

        "structural_fingerprint": fingerprint,
    }

    doc.close()
    pdf.close()

    return report


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="PDF forensic structure/glyph analyzer"
    )

    parser.add_argument(
        "pdf",
        help="PDF file to analyze",
    )

    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output JSON file",
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf)

    if not pdf_path.exists():
        raise SystemExit(
            f"PDF not found: {pdf_path}"
        )

    output = args.output

    if output is None:
        output = (
            pdf_path.with_suffix("")
            .as_posix()
            + "_forensic.json"
        )

    report = analyze_pdf(pdf_path)

    with open(
        output,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("=" * 60)
    print("FORENSIC ANALYSIS COMPLETE")
    print("=" * 60)

    print(
        "PDF SHA256:",
        report["file"]["sha256"],
    )

    structure = report["structure_tree"]

    print(
        "Structure tree:",
        structure["present"],
    )

    print(
        "Nodes:",
        structure["node_count"],
    )

    print(
        "Max depth:",
        structure["max_depth"],
    )

    print(
        "Tables:",
        structure["tables"],
    )

    print(
        "Rows:",
        structure["rows"],
    )

    print(
        "Cells:",
        structure["cells"],
    )

    print(
        "Figures:",
        structure["figures"],
    )

    print(
        "NonStruct:",
        structure["nonstruct"],
    )

    print(
        "Fonts:",
        len(report["fonts"]),
    )

    print(
        "Characters:",
        report["glyph_usage"]["total_characters"],
    )

    print(
        "Images:",
        len(report["images"]),
    )

    print(
        "STRUCTURAL FINGERPRINT:",
        report["structural_fingerprint"]["sha256"],
    )

    print()
    print("JSON:", output)


if __name__ == "__main__":
    main()