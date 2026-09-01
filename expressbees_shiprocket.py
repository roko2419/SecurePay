"""
Shiprocket-style 4x6 shipping label generator.

Byte-for-byte layout match with the reference label: 288 x 432 pt page,
Base-14 fonts (Helvetica / Times), Code 128 barcodes, and the same frame
quads, table grid segments and text baselines as the original PDF.

    pip install reportlab

    python shipping_label.py                  # writes shipping_label.pdf
    python shipping_label.py out.pdf          # custom output path

To generate a different label, edit the LabelData instance at the bottom
or import build_label and pass your own.
"""

import base64
import io
import sys
from dataclasses import dataclass, field
from typing import List

from reportlab.graphics.barcode import code128
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

NBSP = "\u00a0"   # the original template uses non-breaking spaces in a few spots

# --------------------------------------------------------------------------
# Geometry, taken directly from the reference PDF's content stream.
# Points, reportlab coordinates (origin bottom-left).
# --------------------------------------------------------------------------

PAGE_W, PAGE_H = 288.0, 432.0

# Frame borders and section rules, drawn as filled quads exactly as the
# original does. Each entry is (4 corner points, is_grey).
FRAME_QUADS = [
    # Main body box
    (((4.500, 327.000), (283.500, 327.000), (282.000, 326.250), (6.000, 326.250)), False),
    (((4.500, 77.250), (283.500, 77.250), (282.000, 78.750), (6.000, 78.750)), False),
    (((283.500, 327.000), (283.500, 77.250), (282.000, 78.750), (282.000, 326.250)), False),
    (((4.500, 327.000), (4.500, 77.250), (6.000, 78.750), (6.000, 326.250)), False),
    # Section rules: above "Shipped By", above the product table
    (((6.000, 242.001), (282.000, 242.001), (282.000, 242.751), (6.000, 242.751)), False),
    (((6.000, 142.333), (282.000, 142.333), (282.000, 143.083), (6.000, 143.083)), False),
    # Ship To box
    (((4.500, 428.250), (283.500, 428.250), (282.000, 426.750), (6.000, 426.750)), False),
    (((4.500, 326.250), (283.500, 326.250), (282.000, 327.000), (6.000, 327.000)), False),
    (((283.500, 428.250), (283.500, 326.250), (282.000, 327.000), (282.000, 426.750)), False),
    (((4.500, 428.250), (4.500, 326.250), (6.000, 327.000), (6.000, 426.750)), False),
    (((6.000, 327.000), (282.000, 327.000), (282.000, 327.750), (6.000, 327.750)), False),
]

# Divider inside the footer box, between the terms and the notice
FOOTER_QUADS = [
    (((6.000, 50.685), (282.000, 50.685), (281.250, 49.935), (6.750, 49.935)), False),
    (((6.000, 49.185), (282.000, 49.185), (281.250, 49.935), (6.750, 49.935)), True),
    (((282.000, 50.685), (282.000, 49.185), (281.250, 49.935), (281.250, 49.935)), True),
    (((6.000, 50.685), (6.000, 49.185), (6.750, 49.935), (6.750, 49.935)), False),
]

FOOTER_RECT = (5.250, 19.935, 277.500, 58.065)   # stroked at 1.5pt

# Product table
TABLE_COLS = [6.750, 86.010, 110.405, 130.326, 170.394, 217.841, 245.595, 281.250]
TABLE_ROW_YS = [141.583, 131.064, 112.445]       # header top, header bottom, row bottom
# Right-edge padding per column, as produced by the original renderer
CELL_PAD = [None, 1.147, None, 1.032, 0.940, 1.131, 1.136]   # None = centred
VALUE_PAD = [None, 1.147, None, 1.087, 1.087, 1.163, 0.588]

# Barcodes and logo: x, y, width, height
AWB_BARCODE_BOX = (147.750, 277.308, 112.500, 30.000)
ORDER_BARCODE_BOX = (146.190, 176.871, 112.500, 37.500)
LOGO_BOX = (232.500, 22.935, 47.250, 11.250)

GREY = (0.160, 0.160, 0.160)

# Text baselines, lifted verbatim from the reference content stream
SHIPTO_BASELINES = [408.017, 398.109, 388.952, 379.794, 369.887, 359.979, 350.072]
SHIPPER_BASELINES = [216.517, 206.610, 196.702, 186.795, 176.887]
TERMS_BASELINES = [67.674, 58.516]


@dataclass
class LineItem:
    name: str
    sku: str
    hsn: str = ""
    qty: str = "1"
    unit_price: str = "0.00"
    taxable_value: str = "0.00"
    tax: str = "0.00"
    total: str = "0.00"


@dataclass
class LabelData:
    # Ship To
    consignee_name: str
    consignee_address: List[str]          # up to 6 lines
    consignee_phone: str

    # Shipment
    dimensions: str
    payment: str
    cod_amount: str
    weight: str
    ewaybill: str

    # Carrier
    carrier: str
    awb: str
    routing_code: str
    rto_routing_code: str

    # Shipper / return address
    shipper_name: str
    shipper_address: List[str]            # up to 4 lines
    shipper_gstin: str
    shipper_phone: str
    shipper_alt_phone: str

    # Order
    order_no: str
    invoice_no: str
    invoice_date: str

    items: List[LineItem] = field(default_factory=list)
    terms: List[str] = field(default_factory=list)
    tax_label: str = "IGST"
    page_label: str = "1/1"


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def _quad(c, points, grey=False):
    c.setFillColorRGB(*(GREY if grey else (0, 0, 0)))
    p = c.beginPath()
    p.moveTo(*points[0])
    for pt in points[1:]:
        p.lineTo(*pt)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def _left(c, text, x, y, font, size):
    c.setFont(font, size)
    c.drawString(x, y, text)


def _cell(c, text, col, y, font, size, pads):
    """Right-align into a column, or centre it when the pad entry is None."""
    if not text:
        return
    c.setFont(font, size)
    pad = pads[col]
    if pad is None:
        c.drawCentredString((TABLE_COLS[col] + TABLE_COLS[col + 1]) / 2.0, y, text)
    else:
        c.drawRightString(TABLE_COLS[col + 1] - pad, y, text)


def _draw_barcode(c, value, box):
    """
    Code 128, scaled to fill the box exactly.

    The reference sizes every barcode to the same 112.5 pt width, so module
    width differs per payload. Building at a nominal width and scaling
    reproduces that, and keeps the symbol vector rather than raster.
    """
    x, y, w, h = box
    bc = code128.Code128(value, barHeight=h, barWidth=1.0,
                         humanReadable=False, quiet=False, checksum=True)
    c.saveState()
    c.translate(x, y)
    c.scale(w / bc.width, 1.0)
    bc.drawOn(c, 0, 0)
    c.restoreState()


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def _draw_frame(c):
    for pts, grey in FRAME_QUADS:
        _quad(c, pts, grey)
    c.setFillColorRGB(0, 0, 0)


def _draw_ship_to(c, d):
    _left(c, "Ship To ", 8.250, 417.924, "Helvetica-Bold", 7.5)
    lines = [d.consignee_name] + list(d.consignee_address) + [f"Phone No.: {d.consignee_phone}"]
    for text, y in zip(lines, SHIPTO_BASELINES):
        _left(c, text, 9.000, y, "Helvetica-Oblique", 7.5)


def _draw_shipment_block(c, d):
    rows = [
        ("Dimensions:", d.dimensions, "Times-Roman", "Times-Roman", 6.8, 303.149),
        ("Payment:", d.payment, "Times-Roman", "Times-Bold", 6.8, 292.130),
        ("COD Amount:", d.cod_amount, "Times-Bold", "Times-Bold", 8.2, 279.685),
        ("Weight:", d.weight, "Times-Roman", "Times-Roman", 6.8, 268.310),
        ("eWaybill No.:", d.ewaybill, "Times-Roman", "Times-Roman", 6.8, 257.291),
    ]
    for label, value, lfont, vfont, size, y in rows:
        _left(c, label, 10.500, y, lfont, size)
        _left(c, value, 65.516, y, vfont, size)


def _draw_carrier_block(c, d):
    _left(c, f" {d.carrier} ", 174.226, 309.446, "Times-Roman", 9.0)
    _draw_barcode(c, d.awb, AWB_BARCODE_BOX)
    _left(c, d.awb, 180.375, 270.893, "Times-Roman", 6.8)
    _left(c, f"{NBSP}Routing Code: {d.routing_code}", 147.750, 259.874, "Times-Roman", 6.8)
    _left(c, f"{NBSP}RTO Routing Code: {d.rto_routing_code}", 147.750, 248.855, "Times-Roman", 6.8)


def _draw_shipper_block(c, d):
    _left(c, "Shipped By", 8.250, 226.425, "Helvetica-Bold", 7.5)
    _left(c, "(If undelivered, return to)", 49.508, 226.425, "Helvetica", 6.7)
    lines = [d.shipper_name] + list(d.shipper_address)
    for text, y in zip(lines, SHIPPER_BASELINES):
        _left(c, text, 9.000, y, "Helvetica-Oblique", 7.5)
    _left(c, f"GSTIN: {d.shipper_gstin}", 8.250, 166.980, "Helvetica-Oblique", 7.5)
    _left(c, f"Phone No.: {d.shipper_phone}", 9.000, 157.822, "Helvetica-Oblique", 7.5)
    _left(c, f"Alternate No.: - {d.shipper_alt_phone}", 9.000, 147.915, "Helvetica-Oblique", 7.5)


def _draw_order_block(c, d):
    _left(c, f"Order #: {d.order_no} ", 165.750, 216.202, "Helvetica", 7.5)
    _draw_barcode(c, d.order_no, ORDER_BARCODE_BOX)
    _left(c, f"Invoice No.: {d.invoice_no}", 146.190, 166.545, "Helvetica", 7.5)
    _left(c, f"Invoice Date: {d.invoice_date}", 146.190, 157.387, "Helvetica", 7.5)


def _draw_table_grid(c):
    """
    The original strokes every cell edge separately at 1pt, with each segment
    overshooting its neighbours by 0.5pt. The rightmost verticals are grey.
    """
    cols, ys = TABLE_COLS, TABLE_ROW_YS
    c.setLineWidth(1)
    for row in range(len(ys) - 1):
        y_top, y_bot = ys[row], ys[row + 1]
        for line_y in ((y_top, y_bot) if row == 0 else (y_bot,)):
            for i in range(len(cols) - 1):
                c.setStrokeColorRGB(0, 0, 0)
                c.line(cols[i] - 0.5, line_y, cols[i + 1] + 0.5, line_y)
        for i, x in enumerate(cols):
            c.setStrokeColorRGB(*(GREY if i == len(cols) - 1 else (0, 0, 0)))
            c.line(x, y_top + 0.5, x, y_bot - 0.5)
    c.setStrokeColorRGB(0, 0, 0)


def _draw_table(c, d):
    _draw_table_grid(c)

    hy = 133.918
    _left(c, "Product Name & SKU", 8.000, hy, "Times-Bold", 6.8)
    for col, text in enumerate(["HSN", "Qty", "Unit Price", "Taxable Value",
                                d.tax_label, "Total"], start=1):
        _cell(c, text, col, hy, "Times-Bold", 6.8, CELL_PAD)

    if not d.items:
        return
    it = d.items[0]
    _left(c, f"{it.name} ", 8.000, 123.334, "Times-Roman", 6.8)
    _left(c, f"SKU: {it.sku}", 8.000, 115.299, "Times-Roman", 6.8)

    vy = 119.349
    for col, text in enumerate([it.hsn, it.qty, it.unit_price, it.taxable_value,
                                it.tax, it.total], start=1):
        _cell(c, text, col, vy, "Times-Roman", 6.8, VALUE_PAD)


def _draw_footer(c, d):
    x, y, w, h = FOOTER_RECT
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(1.5)
    c.rect(x, y, w, h, stroke=1, fill=0)

    for text, baseline in zip(d.terms, TERMS_BASELINES):
        _left(c, text, 8.250, baseline, "Helvetica", 7.5)

    for pts, grey in FOOTER_QUADS:
        _quad(c, pts, grey)
    c.setFillColorRGB(0, 0, 0)

    _left(c, "THIS IS AN AUTO-GENERATED LABEL AND DOES NOT NEED SIGNATURE.",
          8.250, 31.137, "Helvetica", 5.2)
    _left(c, f"Powered By:{NBSP * 3} ", 244.150, 35.985, "Helvetica", 5.2)

    logo = _load_logo()
    if logo is not None:
        c.drawImage(logo, *LOGO_BOX, mask="auto")

    _left(c, d.page_label, 144.000, 0.750, "Helvetica", 10.0)


def _load_logo():
    try:
        return ImageReader(io.BytesIO(base64.b64decode(LOGO_B64)))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def build_label(data: LabelData, path: str = "shipping_label.pdf") -> str:
    c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Shipping Label")
    _draw_frame(c)
    _draw_ship_to(c, data)
    _draw_shipment_block(c, data)
    _draw_carrier_block(c, data)
    _draw_shipper_block(c, data)
    _draw_order_block(c, data)
    _draw_table(c, data)
    _draw_footer(c, data)
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# Embedded 'Powered By' logo (RGBA PNG, 147x35), so the script is self-contained.
# --------------------------------------------------------------------------

LOGO_B64 = (
    "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"
    "flLG0ku9AAAAAElFTkSuQmCC"
)


# --------------------------------------------------------------------------
# Sample data — matches the reference label exactly
# --------------------------------------------------------------------------

SAMPLE = LabelData(
    consignee_name="Nivrutti Sunil",
    consignee_address=[
        "Near Hanuman Temple,at Post Nilje ",
        "Village,katai Tall Naka,kalyan Shil Road, ",
        "Dombivli (east) Mumbai,maharashtra (india)",
        "Thane, Maharashtra, India",
        "421204",
    ],
    consignee_phone="8108687658",

    dimensions="35.00x35.00x15.00",
    payment="COD",
    cod_amount="2200.00 INR",
    weight="3.00 KG",
    ewaybill="N/A",

    carrier="Xpressbees 5kg",
    awb="14326490245836",
    routing_code="W/S-22/31A/204",
    rto_routing_code="NA",

    shipper_name="Farogh Abbas",
    shipper_address=[
        "Daulat bagh gali no 7 math wa",
        "li gali Near axis bank atm",
        "Moradabad",
        "244001",
    ],
    shipper_gstin="",
    shipper_phone="7055533314",
    shipper_alt_phone="8630301698",

    order_no="3098735559",
    invoice_no="Retail00004",
    invoice_date="2023-06-19",

    items=[LineItem(
        name="Golden set",
        sku="1686864329797",
        hsn="",
        qty="1",
        unit_price="2200.00",
        taxable_value="2200.00",
        tax="0.00",
        total="2200.00",
    )],

    terms=[
        "All disputes are subject to Uttar Pradesh jurisdiction only. Goods once sold will ",
        "only be taken back or exchanged as per the store's exchange/return policy.",
    ],
    tax_label="IGST",
)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "shipping_label.pdf"
    print("Wrote", build_label(SAMPLE, out))