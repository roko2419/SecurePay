"""
Xpressbees / Shiprocket A4 shipping-label generator.

Reproduces the reference PDF: A4 596 x 842 pt, the Firefox print header and
footer in DejaVu Serif, and the label itself redrawn as vector text, rules
and Code 128 barcodes.

The reference label was a 1800 x 1273 raster screenshot embedded in the page,
so every coordinate below was measured off that image and converted to points
(1 image px = 501.75/1800 pt, i.e. 258 PPI). Redrawing it as vector means the
output is sharp at any zoom and the barcodes scan cleanly.

    pip install reportlab

    python xpressbees_label.py               # writes xpressbees_label.pdf
    python xpressbees_label.py out.pdf

Edit the LabelData instance at the bottom, or import build_label.
"""

import sys
from dataclasses import dataclass, field
from typing import List, Optional

from reportlab.graphics.barcode import code128
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# --------------------------------------------------------------------------
# Page and image-space mapping
# --------------------------------------------------------------------------

PAGE_W, PAGE_H = 596.0, 842.0

IMG_X0, IMG_TOP = 47.12, 42.00          # where the label sits on the page
SCALE = 501.75 / 1800.0                 # pt per image pixel (258 PPI)


def X(px: float) -> float:
    """Image x (px) -> page x (pt)."""
    return IMG_X0 + px * SCALE


def Y(py: float) -> float:
    """Image y (px, top-down) -> reportlab y (pt, bottom-up)."""
    return PAGE_H - (IMG_TOP + py * SCALE)


def W(px: float) -> float:
    return px * SCALE


# --------------------------------------------------------------------------
# Colours and type
# --------------------------------------------------------------------------

BLACK = (0, 0, 0)
MAROON = (60 / 255, 33 / 255, 31 / 255)       # table + footer rules
PINK = (230 / 255, 208 / 255, 206 / 255)      # table header fill

# Font sizes, derived from measured string widths on the reference
SZ_HEAD = 5.90      # "DELIVER To:", "SHIPMENT WEIGHT", routing values, COURIER, AWB
SZ_BODY = 4.75      # addresses, invoice, gstin, table cells
SZ_TABLE = 4.55     # SKU / ITEM / QTY / PRICE column headings
SZ_ITEM = 4.15      # long product description
SZ_FINE = 3.56      # terms and conditions
SZ_PREPAID = 8.15   # the big payment word

CAP = 0.717         # Helvetica cap height, as a fraction of em


# The reference is a JPEG screenshot whose glyphs sit half a pixel low
# relative to the measured ink rows; this lines the vector text back up.
BASELINE_NUDGE = 1.5


def _baseline(top_px: float, size_pt: float) -> float:
    """Image-space baseline from the top of the capitals."""
    return top_px + CAP * size_pt / SCALE + BASELINE_NUDGE


# --------------------------------------------------------------------------
# Layout constants, all in image pixels
# --------------------------------------------------------------------------

# Rules are centred on the middle of their pixel span, e.g. a 3 px rule
# occupying image rows 29-31 has its centre at 30.5.
BOX_L, BOX_R, PANEL_R = 30.5, 1769.5, 900.0   # outer frame and centre divider
BOX_T, BOX_B = 30.5, 1242.5

# Full-width rules across the left panel: (y, thickness_px, colour)
RULES = [
    (306.5, 3, BLACK),     # under the addresses
    (412.5, 3, BLACK),     # under the order barcode
    (485.0, 2, BLACK),     # under weight / dimensions
    (636.5, 1, MAROON),    # top of the item table
    (673.0, 2, MAROON),    # under the table heading row
    (703.0, 1, MAROON),    # under the item row
    (733.5, 1, MAROON),    # under the total row
    (1133.5, 1, MAROON),   # above the invoice line
    (1194.5, 1, MAROON),   # above terms and conditions
    (1218.5, 1, MAROON),   # above the disputes line
]

# Item table
TBL_TOP, TBL_HDR, TBL_ITEM, TBL_TOTAL = 636.5, 673.0, 703.0, 733.5
TBL_COLS = [30.5, 250.5, 765.5, 808.0, 898.5]        # SKU | ITEM | QTY | PRICE

# Barcode ink boxes: x, y_top, width, height (px)
ORDER_BC = (78.0, 339.0, 117.0, 63.0)
AWB_BC = (484.0, 569.0, 275.0, 53.0)

# Firefox print chrome
CHROME_FONT_SIZE = 10.0
CHROME_HEADER_Y = 9.5        # baseline, measured from page top
CHROME_FOOTER_Y = 839.5
CHROME_URL_X = 395.51
CHROME_DATE_X = 515.90


@dataclass
class LineItem:
    sku: str
    description: str
    qty: str
    price: str


@dataclass
class LabelData:
    # DELIVER To
    consignee_name: str
    consignee_address: List[str]      # up to 2 lines in the upper block
    consignee_city: str
    consignee_region: str             # "Karnataka, 560024, India"
    consignee_mobile: str

    # Shipped By
    shipper_name: str
    shipper_address: List[str]        # up to 3 lines
    shipper_region: str               # "Dakshina Kannada, Karnataka"
    shipper_tail: str                 # "575008, India,Mobile No.: 7204176602"

    order_no: str
    weight: str
    dimensions: str
    routing_code: str
    rto_routing_code: str
    payment_mode: str                 # "PREPAID" / "COD"
    courier: str
    awb: str

    items: List[LineItem]
    total: str

    invoice_no: str
    invoice_date: str
    gstin: str
    jurisdiction: str

    # Browser print chrome; set to None to omit
    chrome_title: Optional[str] = "Firefox"
    chrome_url: Optional[str] = None
    chrome_page: Optional[str] = "1 of 1"
    chrome_date: Optional[str] = None

    terms: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def _text(c, s, x_px, top_px, size, bold=False, colour=BLACK):
    if not s:
        return
    c.setFillColorRGB(*colour)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(X(x_px), Y(_baseline(top_px, size)), s)


def _centred(c, s, x0_px, x1_px, top_px, size, bold=False, colour=BLACK):
    c.setFillColorRGB(*colour)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawCentredString((X(x0_px) + X(x1_px)) / 2.0, Y(_baseline(top_px, size)), s)


def _right(c, s, x_px, top_px, size, bold=False, colour=BLACK):
    c.setFillColorRGB(*colour)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawRightString(X(x_px), Y(_baseline(top_px, size)), s)


def _hline(c, y_px, x0_px, x1_px, thick_px, colour):
    c.setStrokeColorRGB(*colour)
    c.setLineWidth(W(thick_px))
    c.line(X(x0_px), Y(y_px), X(x1_px), Y(y_px))


def _vline(c, x_px, y0_px, y1_px, thick_px, colour):
    c.setStrokeColorRGB(*colour)
    c.setLineWidth(W(thick_px))
    c.line(X(x_px), Y(y0_px), X(x_px), Y(y1_px))


def _barcode(c, value, box):
    """Code 128 scaled so the printed bars fill the measured ink box."""
    x_px, top_px, w_px, h_px = box
    bc = code128.Code128(value, barHeight=W(h_px), barWidth=1.0,
                         humanReadable=False, quiet=False, checksum=True)
    c.saveState()
    c.setFillColorRGB(*BLACK)
    c.translate(X(x_px), Y(top_px + h_px))
    c.scale(W(w_px) / bc.width, 1.0)
    bc.drawOn(c, 0, 0)
    c.restoreState()


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def _draw_frame(c):
    # Outer box, spanning both panels, plus the centre divider
    for y, t in ((BOX_T, 3), (BOX_B, 3)):
        _hline(c, y, BOX_L - 1.5, BOX_R + 1.5, t, BLACK)
    for x, t in ((BOX_L, 3), (PANEL_R, 3), (BOX_R, 3)):
        _vline(c, x, BOX_T, BOX_B, t, BLACK)
    # Rules across the left panel only
    for y, t, col in RULES:
        _hline(c, y, BOX_L, PANEL_R, t, col)


def _draw_addresses(c, d):
    _text(c, "DELIVER To:", 38, 37, SZ_HEAD)
    _text(c, d.consignee_name, 48, 67, SZ_BODY, bold=True)
    for line, top in zip(d.consignee_address, (91, 115)):
        _text(c, line, 49, top, SZ_BODY, bold=True)
    _text(c, d.consignee_city, 54, 188, SZ_BODY, bold=True)
    _text(c, d.consignee_region, 49, 212, SZ_BODY, bold=True)
    _text(c, f"MOBILE NO. : {d.consignee_mobile}", 49, 237, SZ_BODY, bold=True)

    _text(c, "Shipped By (If undelivered, return to) :", 467, 36, SZ_HEAD)
    _text(c, d.shipper_name, 467, 67, SZ_BODY, bold=True)
    for line, top in zip(d.shipper_address, (115, 140, 164)):
        _text(c, line, 467, top, SZ_BODY, bold=True)
    _text(c, d.shipper_region, 472, 212, SZ_BODY, bold=True)
    _text(c, d.shipper_tail, 467, 237, SZ_BODY, bold=True)


def _draw_order(c, d):
    _text(c, f"ORDER # : {d.order_no}", 79, 315, SZ_BODY)
    _barcode(c, d.order_no, ORDER_BC)


def _draw_shipment(c, d):
    _text(c, f"SHIPMENT WEIGHT : {d.weight}", 61, 427, SZ_HEAD)
    _text(c, f"DIMENSIONS : {d.dimensions}", 62, 457, SZ_HEAD)
    _text(c, "ROUTING CODE :", 485, 427, SZ_BODY)
    _text(c, d.routing_code, 637, 427, SZ_HEAD)
    _text(c, "RTO ROUTING CODE :", 485, 457, SZ_BODY)
    _text(c, d.rto_routing_code, 680, 457, SZ_HEAD)

    _text(c, d.payment_mode, 62, 506, SZ_PREPAID, bold=True)
    _text(c, f"COURIER : {d.courier}", 485, 499, SZ_HEAD)
    _text(c, "AWB  # :", 484, 546, SZ_HEAD)
    _text(c, d.awb, 577, 546, SZ_HEAD)
    _barcode(c, d.awb, AWB_BC)


def _draw_table_fill(c):
    """Drawn before the frame so the table's top rule stays visible."""
    c.setFillColorRGB(*PINK)
    c.rect(X(BOX_L), Y(TBL_HDR), X(TBL_COLS[-1]) - X(BOX_L), Y(TBL_TOP) - Y(TBL_HDR),
           stroke=0, fill=1)


def _draw_table(c, d):
    # Column dividers: the two inner ones stop at the item row, the QTY/PRICE
    # divider carries on through the total row.
    for x in TBL_COLS[1:3]:
        _vline(c, x, TBL_TOP, TBL_ITEM, 1, MAROON)
    _vline(c, TBL_COLS[3], TBL_TOP, TBL_TOTAL, 2, MAROON)
    _vline(c, TBL_COLS[4], TBL_TOP, TBL_TOTAL, 3, MAROON)

    for label, i, top in (("SKU", 0, 647), ("ITEM", 1, 648),
                          ("QTY", 2, 647), ("PRICE", 3, 647)):
        _centred(c, label, TBL_COLS[i], TBL_COLS[i + 1], top, SZ_TABLE, bold=True)

    if d.items:
        it = d.items[0]
        _text(c, it.sku, 37, 681, SZ_BODY)
        _text(c, it.description, 257, 682, SZ_ITEM)
        _right(c, it.qty, 798, 681, SZ_BODY)
        _right(c, it.price, 892, 681, SZ_BODY)

    _right(c, "TOTAL", 801, 711, SZ_BODY)
    _right(c, d.total, 892, 711, SZ_BODY)


def _draw_footer(c, d):
    _text(c, f"Invoice No. : {d.invoice_no} | Invoice Date : {d.invoice_date}",
          44, 1085, SZ_BODY)
    _text(c, f"Gstin No : {d.gstin}", 43, 1109, SZ_BODY)
    _text(c, "TERMS AND CONDITIONS:", 42, 1140, SZ_BODY)
    for line, top in zip(d.terms, (1161, 1179)):
        _text(c, line, 43 if top == 1161 else 42, top, SZ_FINE)
    _text(c, f"All disputes are subject to {d.jurisdiction} jurisdiction. Goods once sold "
             f"will only be taken back or exchanged as per the store's exchange/return policy.",
          42, 1200, SZ_FINE)
    _text(c, "THIS IS AN AUTO-GENERATED LABEL AND DOES NOT NEED SIGNATURE.",
          42, 1225, SZ_FINE)


def _chrome_font():
    """Firefox prints its header in DejaVu Serif; fall back to Times."""
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
                 "C:/Windows/Fonts/DejaVuSerif.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSerif", path))
            return "DejaVuSerif"
        except Exception:
            continue
    return "Times-Roman"


def _draw_chrome(c, d):
    font = _chrome_font()
    c.setFillColorRGB(*BLACK)
    c.setFont(font, CHROME_FONT_SIZE)
    if d.chrome_title:
        c.drawString(0, PAGE_H - CHROME_HEADER_Y, d.chrome_title)
    if d.chrome_url:
        c.drawString(CHROME_URL_X, PAGE_H - CHROME_HEADER_Y, d.chrome_url)
    if d.chrome_page:
        c.drawString(0, PAGE_H - CHROME_FOOTER_Y, d.chrome_page)
    if d.chrome_date:
        c.drawString(CHROME_DATE_X, PAGE_H - CHROME_FOOTER_Y, d.chrome_date)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def build_label(data: LabelData, path: str = "xpressbees_label.pdf") -> str:
    c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Shipping Label")
    _draw_chrome(c, data)
    _draw_table_fill(c)
    _draw_frame(c)
    _draw_addresses(c, data)
    _draw_order(c, data)
    _draw_shipment(c, data)
    _draw_table(c, data)
    _draw_footer(c, data)
    c.showPage()
    c.save()
    return path


SAMPLE = LabelData(
    consignee_name="Tabreez Ahamed",
    consignee_address=["Sri Gowri Nilaya, House No. 15, 4t-",
                       "h Cross, Vinayaknagar, Hebbal"],
    consignee_city="Bangalore",
    consignee_region="Karnataka, 560024, India",
    consignee_mobile="8050686042",

    shipper_name="Monsterleaf",
    shipper_address=["2-13/6 , Bondel Junction , Achukod-",
                     "i Road , Bondel, Mangalore Opp MGC",
                     "School Ground , Temple Dwara Road"],
    shipper_region="Dakshina Kannada, Karnataka",
    shipper_tail="575008, India,Mobile No.: 7204176602",

    order_no="1031",
    weight="0.1 KG",
    dimensions="15x4x1",
    routing_code="S2/S-56/6B/024",
    rto_routing_code="RTO-S2/S-17/05",
    payment_mode="PREPAID",
    courier="Xpressbees Surface",
    awb="141123202676297",

    items=[LineItem(
        sku="ML-BR-02",
        description="Bamboo Toothbrush - Charcoal Bristles (Pack Of 2) - Pack of 2...",
        qty="1",
        price="Rs.159.0",
    )],
    total="Rs.159.00",

    invoice_no="ML/2020/00028",
    invoice_date="2020-07-07 11:46:00",
    gstin="29GEGPS6413M1ZR",
    jurisdiction="Karnataka",

    chrome_title="Firefox",
    chrome_url="https://online.fliphtml5.com/izsyq/yvqn/",
    chrome_page="1 of 1",
    chrome_date="10/01/25, 08:40",

    terms=[
        "1. Visit official website of Xpressbees Surface to view the Conditions of Carriage.",
        "2. Shipping charges are inclusive of service tax and all figures are in INR.",
    ],
)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "xpressbees_label.pdf"
    print("Wrote", build_label(SAMPLE, out))