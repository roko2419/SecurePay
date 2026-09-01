#!/usr/bin/env python3
"""
generate_cod_label.py

Generates a Cash-on-Delivery courier shipping-label PDF in the common
Indian e-commerce label style: receiver / sender blocks, an order-number
barcode, weight & dimensions, a COD collection box, courier name + AWB
barcode, an item table, an invoice/GST footer, and a terms-and-conditions
block.

Everything printed on the label comes from the LABEL_DATA dict below -
edit it and re-run. Both barcodes are real Code128 barcodes rendered
live from whatever order number / AWB number you put in LABEL_DATA, so
the printed number and the scannable barcode always match each other.

Usage:
    python3 generate_cod_label.py [output.pdf]
"""

import sys
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128

# ------------------------------------------------------------------
# 1. EDIT THIS: every field shown on the label lives here
# ------------------------------------------------------------------
LABEL_DATA = {
    "deliver_to": {
        "name": "Jane Sample",
        "address": ["123 Example Layout", "Sample Nagar"],
        "city": "Sample City",
        "state_line": "Karnataka, 560001, India",
        "mobile": "9999999999",
    },
    "shipped_by": {
        "name": "Your Company Pvt Ltd",
        "address": ["Plot No. 1, Sample Industrial Area,", "Sample Village"],
        "city_line": "Sample City, Sample State",
        "pin_line": "100001, India, Mobile No.: 9999999999",
        "alternate": "9999999999",
        "care": "9999999999 | care@example.com",
    },
    "order_no": "1001",
    "weight_kg": "0.20",
    "dimensions_cm": "10*10*10",
    "routing_code": "NA",
    "sort_code": "S01",
    "cod_amount": "1,380",
    "courier_name": "Sample Courier Services",
    "awb_no": "SC1234567890AB",
    "items": [
        {"sku": "10000000000001", "item": "Sample Product Name Goes Here", "qty": 1, "price": "1,380.00"},
    ],
    "invoice_no": "Retail00001",
    "invoice_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # stamps the moment the script runs
    "gstin": "07AAAAA0000A1Z5",  # AAAAA0000A is the standard placeholder PAN pattern
}

OUTPUT_PATH = sys.argv[1] if len(sys.argv) > 1 else "cod_label.pdf"

# ------------------------------------------------------------------
# 2. Styling constants
# ------------------------------------------------------------------
RED = HexColor("#800000")   # verified: box-border stroke color in the source PDF
PINK = HexColor("#e6cfcf")  # verified: item-table header fill color in the source PDF
BLACK = HexColor("#000000")

F_REG = "Helvetica"
F_BOLD = "Helvetica-Bold"

MARGIN = 12 * mm
PAGE_W, PAGE_H = A4


def draw_barcode(c, value, x, y, height=14 * mm, bar_width=0.4 * mm):
    """Draw a Code128 barcode whose bars encode `value` exactly (scannable)."""
    bc = code128.Code128(value, barHeight=height, barWidth=bar_width, humanReadable=False)
    bc.drawOn(c, x, y)
    return bc.width


def text(c, x, y, s, font=F_REG, size=8, color=BLACK):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(x, y, s)


def build_label(c, d):
    box_x = MARGIN
    box_w = PAGE_W - 2 * MARGIN
    y = PAGE_H - MARGIN  # cursor: top edge of the next row
    pad = 3 * mm

    c.setStrokeColor(BLACK)
    c.setLineWidth(0.8)

    # ---------- Header row: Deliver To | Shipped By | (blank) ----------
    col1_w = box_w * 0.34
    col2_w = box_w * 0.34
    row_h = 40 * mm

    c.rect(box_x, y - row_h, box_w, row_h)
    c.line(box_x + col1_w, y - row_h, box_x + col1_w, y)
    c.line(box_x + col1_w + col2_w, y - row_h, box_x + col1_w + col2_w, y)

    ty = y - pad - 3 * mm
    text(c, box_x + pad, ty, "DELIVER To:", F_BOLD, 8)
    ty -= 5 * mm
    text(c, box_x + pad, ty, d["deliver_to"]["name"], F_BOLD, 8.5)
    ty -= 4.2 * mm
    for line in d["deliver_to"]["address"]:
        text(c, box_x + pad, ty, line, F_REG, 8)
        ty -= 4.2 * mm
    ty -= 2 * mm
    text(c, box_x + pad, ty, d["deliver_to"]["city"], F_REG, 8)
    ty -= 4.2 * mm
    text(c, box_x + pad, ty, d["deliver_to"]["state_line"], F_BOLD, 8)
    ty -= 4.8 * mm
    text(c, box_x + pad, ty, f"MOBILE NO. : {d['deliver_to']['mobile']}", F_BOLD, 8)

    tx2 = box_x + col1_w + pad
    ty = y - pad - 3 * mm
    text(c, tx2, ty, "Shipped By (If undelivered, return to) :", F_BOLD, 8)
    ty -= 5 * mm
    text(c, tx2, ty, d["shipped_by"]["name"], F_BOLD, 8.5)
    ty -= 5.5 * mm
    for line in d["shipped_by"]["address"]:
        text(c, tx2, ty, line, F_REG, 7.5)
        ty -= 4 * mm
    ty -= 2 * mm
    text(c, tx2, ty, d["shipped_by"]["city_line"], F_BOLD, 8)
    ty -= 4.2 * mm
    text(c, tx2, ty, d["shipped_by"]["pin_line"], F_REG, 7.5)
    ty -= 4 * mm
    text(c, tx2, ty, f"Alternate No.: {d['shipped_by']['alternate']}", F_REG, 7.5)
    ty -= 4 * mm
    text(c, tx2, ty, f"Customer Care No. & Email: {d['shipped_by']['care']}", F_REG, 7.5)

    y -= row_h

    # ---------- Order # + barcode ----------
    row_h = 26 * mm
    c.rect(box_x, y - row_h, box_w, row_h)
    text(c, box_x + pad, y - pad - 3 * mm, f"ORDER # : {d['order_no']}", F_BOLD, 9)
    draw_barcode(c, d["order_no"], box_x + pad, y - row_h + 5 * mm, height=13 * mm, bar_width=0.5 * mm)

    y -= row_h

    # ---------- Weight/Dimensions | Routing/Sort ----------
    row_h = 16 * mm
    split = box_w * 0.45
    c.rect(box_x, y - row_h, box_w, row_h)
    c.line(box_x + split, y - row_h, box_x + split, y)
    text(c, box_x + pad, y - 6 * mm, f"WEIGHT : {d['weight_kg']} kg", F_REG, 8.5)
    text(c, box_x + pad, y - 11 * mm, f"DIMENSIONS : {d['dimensions_cm']}(cm)", F_REG, 8.5)
    text(c, box_x + split + pad, y - 6 * mm, f"ROUTING CODE : {d['routing_code']}", F_REG, 8.5)
    text(c, box_x + split + pad, y - 11 * mm, f"SORT CODE :  {d['sort_code']}", F_REG, 8.5)

    y -= row_h

    # ---------- COD box | Courier + AWB barcode ----------
    row_h = 30 * mm
    split = box_w * 0.45
    c.rect(box_x, y - row_h, box_w, row_h)
    c.line(box_x + split, y - row_h, box_x + split, y)

    text(c, box_x + pad, y - 10 * mm, "CASH ON DELIVERY", F_BOLD, 14, BLACK)
    text(c, box_x + pad, y - 20 * mm, f"COLLECT COD - Rs.{d['cod_amount']}", F_BOLD, 14, BLACK)

    text(c, box_x + split + pad, y - 6 * mm, f"COURIER : {d['courier_name']}", F_REG, 8.5)
    text(c, box_x + split + pad, y - 13 * mm, f"AWB  # : {d['awb_no']}", F_REG, 8.5)
    draw_barcode(c, d["awb_no"], box_x + split + pad, y - row_h + 4 * mm, height=11 * mm, bar_width=0.35 * mm)

    y -= row_h

    # ---------- Item table ----------
    col_sku_w = box_w * 0.22
    col_item_w = box_w * 0.53
    col_qty_w = box_w * 0.10
    col_price_w = box_w - col_sku_w - col_item_w - col_qty_w  # noqa: F841 (kept for clarity)

    header_h = 6.5 * mm
    c.setFillColor(PINK)
    c.rect(box_x, y - header_h, box_w, header_h, fill=1, stroke=1)
    c.setFillColor(BLACK)
    hy = y - header_h + 2 * mm
    text(c, box_x + 2 * mm, hy, "SKU", F_BOLD, 8)
    text(c, box_x + col_sku_w + 2 * mm, hy, "ITEM", F_BOLD, 8)
    text(c, box_x + col_sku_w + col_item_w + 2 * mm, hy, "QTY", F_BOLD, 8)
    text(c, box_x + col_sku_w + col_item_w + col_qty_w + 2 * mm, hy, "PRICE", F_BOLD, 8)
    c.line(box_x + col_sku_w, y - header_h, box_x + col_sku_w, y)
    c.line(box_x + col_sku_w + col_item_w, y - header_h, box_x + col_sku_w + col_item_w, y)
    c.line(box_x + col_sku_w + col_item_w + col_qty_w, y - header_h, box_x + col_sku_w + col_item_w + col_qty_w, y)
    y -= header_h

    row_h = 6 * mm
    total_qty = 0
    for item in d["items"]:
        c.rect(box_x, y - row_h, box_w, row_h)
        c.line(box_x + col_sku_w, y - row_h, box_x + col_sku_w, y)
        c.line(box_x + col_sku_w + col_item_w, y - row_h, box_x + col_sku_w + col_item_w, y)
        c.line(box_x + col_sku_w + col_item_w + col_qty_w, y - row_h, box_x + col_sku_w + col_item_w + col_qty_w, y)
        ry = y - row_h + 2 * mm
        text(c, box_x + 2 * mm, ry, item["sku"], F_REG, 7.5)
        text(c, box_x + col_sku_w + 2 * mm, ry, item["item"][:60], F_REG, 7.5)
        text(c, box_x + col_sku_w + col_item_w + 2 * mm, ry, str(item["qty"]), F_REG, 7.5)
        text(c, box_x + col_sku_w + col_item_w + col_qty_w + 2 * mm, ry, f"Rs.{item['price']}", F_REG, 7.5)
        total_qty += item["qty"]
        y -= row_h

    c.rect(box_x, y - row_h, box_w, row_h)
    c.line(box_x + col_sku_w + col_item_w + col_qty_w, y - row_h, box_x + col_sku_w + col_item_w + col_qty_w, y)
    ry = y - row_h + 2 * mm
    text(c, box_x + col_sku_w + col_item_w - 12 * mm, ry, "TOTAL", F_BOLD, 7.5)
    text(c, box_x + col_sku_w + col_item_w + 2 * mm, ry, str(total_qty), F_BOLD, 7.5)
    total_amt = sum(float(it["price"].replace(",", "")) * it["qty"] for it in d["items"])
    text(c, box_x + col_sku_w + col_item_w + col_qty_w + 2 * mm, ry, f"Rs.{total_amt:,.2f}", F_BOLD, 7.5)
    y -= row_h

    # ---------- blank gap (matches the original template's empty space) ----------
    y -= 28 * mm

    # ---------- Invoice / GST footer ----------
    text(c, box_x + pad, y, f"Invoice No. : {d['invoice_no']}  |  Invoice Date : {d['invoice_date']}", F_REG, 7.5)
    y -= 4 * mm
    text(c, box_x + pad, y, f"Gstin No : {d['gstin']}", F_REG, 7.5)
    y -= 3 * mm

    # ---------- Terms and conditions ----------
    c.setStrokeColor(RED)
    c.setLineWidth(0.7)
    t_h = 12 * mm
    c.rect(box_x, y - t_h, box_w, t_h)
    text(c, box_x + pad, y - 4 * mm, "TERMS AND CONDITIONS:", F_BOLD, 7.5)
    text(c, box_x + pad, y - 8 * mm, f"1. Visit official website of {d['courier_name']} to view the Conditions of Carriage.", F_REG, 7)
    text(c, box_x + pad, y - 11 * mm, "2. Shipping charges are inclusive of service tax and all figures are in INR.", F_REG, 7)
    y -= t_h

    disputes_h = 6 * mm
    c.rect(box_x, y - disputes_h, box_w, disputes_h)
    text(
        c, box_x + pad, y - 4 * mm,
        "All disputes will be resolved under Sample City jurisdiction. Sold goods are eligible for return or exchange as per store policy.",
        F_REG, 7,
    )
    y -= disputes_h

    auto_h = 6 * mm
    c.rect(box_x, y - auto_h, box_w, auto_h)
    text(c, box_x + pad, y - 4 * mm, "THIS IS AN AUTO-GENERATED LABEL AND DOES NOT NEED SIGNATURE.", F_REG, 7)
    y -= auto_h

    c.setStrokeColor(BLACK)


def main():
    c = canvas.Canvas(OUTPUT_PATH, pagesize=A4)
    build_label(c, LABEL_DATA)
    c.save()
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()