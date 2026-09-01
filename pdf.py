# pip install reportlab
from datetime import datetime
import random

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.graphics.barcode import code128

RED = colors.HexColor("#b30000")
BLUE = colors.HexColor("#0a2a78")

PAGE_W, PAGE_H = A5
MARGIN = 6 * mm
LEFT = MARGIN
RIGHT = PAGE_W - MARGIN
INNER_W = RIGHT - LEFT


def draw_text(c, x, y, s, size=9, bold=False, color=colors.black):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, s)


def hline(c, y):
    c.setStrokeColor(RED)
    c.setLineWidth(1)
    c.line(LEFT, y, RIGHT, y)


def vline(c, x, y1, y2):
    c.setStrokeColor(RED)
    c.setLineWidth(1)
    c.line(x, y1, x, y2)


def barcode128(c, value, x, y, h=7 * mm):
    bc = code128.Code128(value, barHeight=h, barWidth=0.32)
    bc.drawOn(c, x, y)


def rdigits(n):
    return "".join(random.choice("0123456789") for _ in range(n))


def crop_text(c, text, max_width, font="Helvetica", size=9):
    c.setFont(font, size)
    if c.stringWidth(text, font, size) <= max_width:
        return text
    suffix = "..."
    sw = c.stringWidth(suffix, font, size)
    out = ""
    for ch in text:
        if c.stringWidth(out + ch, font, size) + sw > max_width:
            break
        out += ch
    return out + suffix


def make_pdf(path="bluedart_cod_label_final.pdf"):
    # -------- sample values --------
    customer = "Sarthak Chavande"
    addr1 = "Acme Avenue Ambedkar Road Ambedkar Nag-"
    addr2 = "ar Kandivali West 1304, Acme Avenue."
    city = "Mumbai"
    state_pin = "Maharashtra, 400067, India"
    mobile = "9869094746"

    order_no = str(random.randint(1000, 9999))
    cluster = "KBE"
    weight = "0.10 KG"
    dims = "10x10x10"
    routing = "BOM/KBE"
    courier = "Blue Dart Surface"
    awb = "7789" + rdigits(7)

    sku = "4434911842027"
    item = "Charcoal Carg - S"
    qty = "1"
    price = "Rs.1,499.00"
    cod_amt = "1499"

    invoice_no = "Retail00108"
    invoice_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c = canvas.Canvas(path, pagesize=A5)
    c.setTitle("Blue Dart COD Label")

    # outer border
    c.setStrokeColor(RED)
    c.setLineWidth(1.2)
    c.rect(3 * mm, 3 * mm, PAGE_W - 6 * mm, PAGE_H - 6 * mm, stroke=1, fill=0)

    top_y = PAGE_H - MARGIN
    y = top_y

    # section heights
    sec1_h = 52 * mm  # address block
    sec2_h = 20 * mm  # order/cluster
    sec3_h = 13 * mm  # weight/routing
    sec4_h = 25 * mm  # cod + awb
    sec5_h = 20 * mm  # item table
    sec6_h = 22 * mm  # invoice/meta

    # ---------------- SEC 1 ----------------
    y1 = y - sec1_h
    hline(c, y1)

    draw_text(c, LEFT + 2 * mm, y - 8 * mm, "DELIVER TO:", 12, True, BLUE)
    draw_text(c, LEFT + 2 * mm, y - 14 * mm, customer, 10, True)
    draw_text(c, LEFT + 2 * mm, y - 20 * mm, addr1, 10, True)
    draw_text(c, LEFT + 2 * mm, y - 26 * mm, addr2, 10, True)
    draw_text(c, LEFT + 2 * mm, y - 34 * mm, city, 11, True)
    draw_text(c, LEFT + 2 * mm, y - 40 * mm, state_pin, 10, True)
    draw_text(c, LEFT + 2 * mm, y - 46 * mm, f"MOBILE NO. : {mobile}", 10, True)

    right_head_x = LEFT + (INNER_W * 0.58)
    draw_text(c, right_head_x, y - 8 * mm, "Shipped By (If undelivered, return to) :", 10)
    draw_text(c, right_head_x, y - 14 * mm, "HOLY HEADEN", 12, True, BLUE)

    y = y1

    # ---------------- SEC 2 ----------------
    y2 = y - sec2_h
    hline(c, y2)

    draw_text(c, LEFT + 6 * mm, y - 7 * mm, f"ORDER # : {order_no}", 11, False, BLUE)
    draw_text(c, LEFT + (INNER_W * 0.60), y - 7 * mm, f"CLUSTER CODE: {cluster}", 11, False, BLUE)
    barcode128(c, order_no, LEFT + 6 * mm, y - 16 * mm, h=7 * mm)

    y = y2

    # ---------------- SEC 3 ----------------
    y3 = y - sec3_h
    hline(c, y3)

    draw_text(c, LEFT + 4 * mm, y - 7 * mm, f"WEIGHT : {weight}", 11, False, BLUE)
    draw_text(c, LEFT + 4 * mm, y - 12 * mm, f"DIMENSIONS : {dims}", 11, False, BLUE)

    right_x = LEFT + (INNER_W * 0.64)
    routing_txt = crop_text(c, f"ROUTING CODE :  {routing}", RIGHT - right_x - 2 * mm, "Helvetica", 11)
    draw_text(c, right_x, y - 7 * mm, routing_txt, 11, False, BLUE)

    y = y3

    # ---------------- SEC 4 ----------------
    y4 = y - sec4_h
    hline(c, y4)

    draw_text(c, LEFT + 4 * mm, y - 10 * mm, "CASH ON DELIVERY", 16, True, BLUE)
    draw_text(c, LEFT + 4 * mm, y - 19 * mm, f"COLLECT COD - Rs.{cod_amt}", 16, True, BLUE)

    courier_txt = crop_text(c, f"COURIER : {courier}", RIGHT - right_x - 2 * mm, "Helvetica", 11)
    draw_text(c, right_x, y - 8 * mm, courier_txt, 11)

    awb_txt = crop_text(c, f"AWB # : {awb}", RIGHT - right_x - 2 * mm, "Helvetica", 12)
    draw_text(c, right_x, y - 16 * mm, awb_txt, 12, False, BLUE)
    barcode128(c, awb, right_x, y - 23 * mm, h=6 * mm)

    y = y4

    # ---------------- SEC 5 (TABLE) ----------------
    y5 = y - sec5_h
    hline(c, y5)

    # columns within width (no overflow)
    x0 = LEFT
    w_sku = 34 * mm
    w_item = 78 * mm
    w_qty = 10 * mm
    w_price = INNER_W - (w_sku + w_item + w_qty)

    x1 = x0 + w_sku
    x2 = x1 + w_item
    x3 = x2 + w_qty
    x4 = RIGHT

    rh_h = 6 * mm
    rh_i = 8 * mm
    rh_t = 6 * mm

    y_hb = y - rh_h
    y_ib = y_hb - rh_i
    y_tb = y_ib - rh_t

    hline(c, y_hb)
    hline(c, y_ib)
    hline(c, y_tb)

    for xx in [x1, x2, x3]:
        vline(c, xx, y5, y)

    # headers centered
    draw_text(c, x0 + (w_sku / 2) - 6 * mm, y - 4.5 * mm, "SKU", 10, False, BLUE)
    draw_text(c, x1 + (w_item / 2) - 6 * mm, y - 4.5 * mm, "ITEM", 10, False, BLUE)
    draw_text(c, x2 + (w_qty / 2) - 3.5 * mm, y - 4.5 * mm, "QTY", 10, False)
    draw_text(c, x3 + (w_price / 2) - 6 * mm, y - 4.5 * mm, "PRICE", 10, False)

    # row values with clipping
    sku_txt = crop_text(c, sku, w_sku - 3 * mm, "Helvetica", 9)
    item_txt = crop_text(c, item, w_item - 3 * mm, "Helvetica", 9)
    price_txt = crop_text(c, price, w_price - 2 * mm, "Helvetica", 9)

    draw_text(c, x0 + 1.5 * mm, y_hb - 5.5 * mm, sku_txt, 9)
    draw_text(c, x1 + 1.5 * mm, y_hb - 5.5 * mm, item_txt, 9)
    draw_text(c, x2 + 3 * mm, y_hb - 5.5 * mm, qty, 9)
    draw_text(c, x3 + 1.5 * mm, y_hb - 5.5 * mm, price_txt, 9)

    draw_text(c, x2 - 16 * mm, y_ib - 4.5 * mm, "TOTAL", 10)
    draw_text(c, x2 + 3 * mm, y_ib - 4.5 * mm, qty, 9)
    draw_text(c, x3 + 1.5 * mm, y_ib - 4.5 * mm, price_txt, 9)

    y = y5

    # ---------------- SEC 6 ----------------
    y6 = y - sec6_h
    hline(c, y6)

    inv_left = f"Invoice No. : {invoice_no}"
    inv_right = f"Invoice Date : {invoice_dt}"

    draw_text(c, LEFT + 2 * mm, y - 8 * mm, inv_left, 11, False, BLUE)
    draw_text(
        c,
        LEFT + 50 * mm,
        y - 8 * mm,
        crop_text(c, inv_right, RIGHT - (LEFT + 50 * mm) - 2 * mm, "Helvetica", 11),
        11,
        False,
        BLUE,
    )
    draw_text(c, LEFT + 2 * mm, y - 14 * mm, "Gstin No :", 11, False, BLUE)

    y = y6

    # ---------------- SEC 7 ----------------
    draw_text(c, LEFT + 2 * mm, y - 7 * mm, "TERMS AND CONDITIONS:", 11)
    draw_text(c, LEFT + 2 * mm, y - 12 * mm, "1. Visit official website of Blue Dart Surface to view the Conditions of Carriage.", 6)
    draw_text(c, LEFT + 2 * mm, y - 16 * mm, "2. Shipping charges are inclusive of service tax and all figures are in INR.", 6)
    draw_text(
        c,
        LEFT + 2 * mm,
        y - 21 * mm,
        "All disputes are subject to Maharashtra jurisdiction only. Goods once sold will only be taken back or exchanged as per the store's exchange/return policy.",
        5.5,
        False,
        RED,
    )
    draw_text(c, LEFT + 2 * mm, y - 28 * mm, "THIS IS AN AUTO-GENERATED LABEL AND DOES NOT NEED SIGNATURE.", 8)

    c.showPage()
    c.save()
    print(f"Generated: {path}")


# if __name__ == "__main__":
#     make_pdf()


from pypdf import PdfReader

pdf_path = "Shipping Label.pdf"
reader = PdfReader(pdf_path)

meta = reader.metadata
print("Raw metadata:", meta)

print("Title:", meta.get("/Title"))
print("Author:", meta.get("/Author"))
print("Creator:", meta.get("/Creator"))
print("Producer:", meta.get("/Producer"))
print("CreationDate:", meta.get("/CreationDate"))
print("ModDate:", meta.get("/ModDate"))
print("Pages:", len(reader.pages))