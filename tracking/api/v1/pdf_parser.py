import io
import re
import logging
from typing import Dict, List

import pdfplumber
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from pypdf import PdfReader

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class PDFTrackingView(View):
    """
    POST /shipment/pdf/upload
    form-data:
      - file: PDF

    Extract (no OCR):
      - courier (delhivery / bluedart / unknown)
      - customer_name
      - order_id
      - shipment_id (AWB/tracking)
    """

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return JsonResponse({"ok": False, "error": "file is required"}, status=400)

        if not file_obj.name.lower().endswith(".pdf"):
            return JsonResponse(
                {"ok": False, "error": "only PDF file allowed"}, status=400
            )

        try:
            text = self._extract_pdf_text(file_obj)
            if not text.strip():
                return JsonResponse(
                    {"ok": False, "error": "no extractable text found in pdf"},
                    status=422,
                )

            courier = self._detect_courier(text)

            if courier == "shiprocket":
                parsed = self._parse_shiprocket(text)
            elif courier == "delhivery":
                parsed = self._parse_delhivery(text)
            elif courier == "bluedart":
                parsed = self._parse_bluedart(text)
            else:
                d = self._parse_delhivery(text)
                b = self._parse_bluedart(text)
                s = self._parse_shiprocket(text)
                parsed = max([d, b, s], key=self._score)
                parsed["courier"] = parsed.get("courier") or "unknown"

            # hard fallback for shipment id
            if not parsed.get("shipment_id"):
                m = re.search(r"\b(\d{10,18})\b", text)
                if m:
                    parsed["shipment_id"] = m.group(1)

            logger.info(
                "PDF PARSED | courier=%s | customer_name=%s | order_id=%s | shipment_id=%s | filename=%s",
                parsed.get("courier", ""),
                parsed.get("customer_name", ""),
                parsed.get("order_id", ""),
                parsed.get("shipment_id", ""),
                file_obj.name,
            )

            return JsonResponse(
                {
                    "ok": True,
                    "filename": file_obj.name,
                    "parsed": {
                        "courier": parsed.get("courier", "unknown"),
                        "customer_name": parsed.get("customer_name", ""),
                        "order_id": parsed.get("order_id", ""),
                        "shipment_id": parsed.get("shipment_id", ""),
                    },
                },
                status=200,
            )

        except Exception as e:
            logger.exception("PDF parse failed")
            return JsonResponse({"ok": False, "error": str(e)}, status=500)

    # ------------------------ helpers ------------------------

    def _extract_pdf_text(self, file_obj) -> str:
        """
        Text extraction from PDF only (no OCR).
        """
        raw = file_obj.read()
        all_text: List[str] = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                all_text.append(t)
        return "\n".join(all_text)

    def _normalize_lines(self, text: str) -> List[str]:
        lines = []
        for ln in text.splitlines():
            ln = re.sub(r"\s+", " ", ln).strip()
            if ln:
                lines.append(ln)
        return lines

    def _detect_courier(self, text: str) -> str:
        t = text.lower()

        if "delhivery" in t:
            return "delhivery"

        # shiprocket-like pattern (even if keyword missing)
        has_awb = re.search(r"\bawb\s*[:#]?\s*[a-z0-9\-]+\b", t) is not None
        has_order_hash = re.search(r"\border\s*#\s*:\s*[a-z0-9\-_\/]+\b", t) is not None
        has_eway = "ewaybill" in t
        has_rto = "rto routing code" in t
        if (
            "shiprocket" in t
            or (has_awb and has_order_hash)
            or (has_awb and (has_eway or has_rto))
        ):
            return "shiprocket"

        if "blue dart" in t or "bluedart" in t:
            return "bluedart"

        return "unknown"

    def _score(self, d: Dict[str, str]) -> int:
        score = 0
        if d.get("customer_name"):
            score += 1
        if d.get("order_id"):
            score += 1
        if d.get("shipment_id"):
            score += 1
        return score

    # ------------------------ parsers ------------------------

    def _parse_bluedart(self, text: str, page_words=None) -> dict:
        """
        BlueDart parser:
        - order_id from ORDER #
        - shipment_id from AWB #
        - customer_name from line below DELIVER TO (prefer positional words if provided)
        """
        import re

        order_id = ""
        shipment_id = ""
        customer_name = ""

        # -------------------------
        # IDs from text
        # -------------------------
        m = re.search(
            r"\bORDER\s*#?\s*[:\-]?\s*([A-Za-z0-9\-_\/]+)\b", text, re.IGNORECASE
        )
        if m:
            order_id = m.group(1).strip()

        m = re.search(
            r"\bAWB\s*#?\s*[:\-]?\s*([A-Za-z0-9\-_\/]+)\b", text, re.IGNORECASE
        )
        if m:
            shipment_id = m.group(1).strip()

        # -------------------------
        # helper: group words into visual lines
        # -------------------------
        def _group_words_to_lines(words, y_tol=3):
            if not words:
                return []
            ws = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
            lines, cur = [], [ws[0]]
            cur_y = ws[0]["top"]

            for w in ws[1:]:
                if abs(w["top"] - cur_y) <= y_tol:
                    cur.append(w)
                else:
                    lines.append(cur)
                    cur = [w]
                    cur_y = w["top"]
            lines.append(cur)

            out = []
            for line in lines:
                line = sorted(line, key=lambda w: w["x0"])
                out.append(
                    {
                        "text": " ".join(x["text"] for x in line).strip(),
                        "words": line,
                        "top": min(x["top"] for x in line),
                    }
                )
            return out

        # -------------------------
        # 1) Prefer positional extraction if page_words provided
        # -------------------------
        # page_words expected format:
        #   - list of words for first page OR
        #   - list of pages where first item is page-1 words
        words = None
        if page_words:
            if isinstance(page_words, list) and len(page_words) > 0:
                # if nested list (pages)
                if isinstance(page_words[0], list):
                    words = page_words[0]
                # if direct words list
                elif isinstance(page_words[0], dict):
                    words = page_words

        if words:
            lines = _group_words_to_lines(words, y_tol=3)
            max_x = max((w["x1"] for w in words), default=600)
            left_limit = max_x * 0.52  # left column cutoff

            deliver_idx = -1
            for i, ln in enumerate(lines):
                left_words = [w for w in ln["words"] if w["x0"] <= left_limit]
                left_text = " ".join(w["text"] for w in left_words).upper()
                if "DELIVER" in left_text and "TO" in left_text:
                    deliver_idx = i
                    break

            if deliver_idx != -1:
                bad_tokens = (
                    "SHIPPED",
                    "MOBILE",
                    "ORDER",
                    "CLUSTER",
                    "WEIGHT",
                    "DIMENSIONS",
                    "ROUTING",
                    "COURIER",
                    "AWB",
                    "CASH",
                    "COLLECT",
                    "INVOICE",
                    "GSTIN",
                )
                for j in range(deliver_idx + 1, min(deliver_idx + 6, len(lines))):
                    ln = lines[j]
                    left_words = [w for w in ln["words"] if w["x0"] <= left_limit]
                    cand = " ".join(w["text"] for w in left_words).strip()
                    up = cand.upper()

                    if not cand:
                        continue
                    if any(t in up for t in bad_tokens):
                        continue
                    if re.search(r"\d", cand):  # avoid address with numbers
                        continue
                    if "," in cand:
                        continue
                    if len(cand.split()) > 4:
                        continue
                    if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,60}", cand):
                        customer_name = " ".join(x.capitalize() for x in cand.split())
                        break

        # -------------------------
        # 2) Fallback: pure text regex between DELIVER TO and ORDER #
        # -------------------------
        if not customer_name:
            t = text.replace("\r", "\n")
            z = ""
            mz = re.search(
                r"DELIVER\s*TO\s*:?(.*?)(ORDER\s*#|CLUSTER\s*CODE|WEIGHT\s*:|AWB\s*#|CASH\s+ON\s+DELIVERY)",
                t,
                re.IGNORECASE | re.DOTALL,
            )
            if mz:
                z = mz.group(1)
            else:
                m2 = re.search(r"DELIVER\s*TO\s*:?(.*)", t, re.IGNORECASE | re.DOTALL)
                z = m2.group(1)[:1000] if m2 else ""

            lines = [re.sub(r"\s+", " ", ln).strip(" :-\t") for ln in z.split("\n")]
            lines = [ln for ln in lines if ln]

            bad_words = (
                "SHIPPED BY",
                "IF UNDELIVERED",
                "RETURN TO",
                "MOBILE NO",
                "ORDER",
                "CLUSTER",
                "ROUTING",
                "COURIER",
                "AWB",
                "WEIGHT",
                "DIMENSIONS",
                "CASH ON DELIVERY",
                "COLLECT COD",
                "INVOICE",
                "GSTIN",
            )

            for ln in lines[:8]:
                cand = re.split(r"\s{3,}|\t|\|", ln)[0].strip()
                up = cand.upper()
                if not cand:
                    continue
                if any(b in up for b in bad_words):
                    continue
                if re.search(r"\d", cand):
                    continue
                if "," in cand:
                    continue
                if re.search(
                    r"\b(ROAD|RD|STREET|ST|NAGAR|LANE|AVE|AVENUE|WEST|EAST|MUMBAI|INDIA|MAHARASHTRA)\b",
                    up,
                ):
                    continue
                if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,60}", cand):
                    customer_name = " ".join(x.capitalize() for x in cand.split())
                    break

        return {
            "courier": "bluedart",
            "customer_name": customer_name,
            "order_id": order_id,
            "shipment_id": shipment_id,
        }

    def _parse_delhivery(self, text: str) -> dict:
        lines = self._normalize_lines(text)

        shipment_id = ""
        customer_name = ""
        order_id = ""

        # 1) shipment id: first long numeric token (top barcode)
        for ln in lines:
            m = re.search(r"\b(\d{12,18})\b", ln)
            if m:
                shipment_id = m.group(1)
                break

        bad_name_words = {"PRE-PAID", "SURFACE", "MUMBAI", "PIN", "ADDRESS", "DATE"}
        for i, ln in enumerate(lines):
            if re.search(r"^Ship\s*To\s*:?\s*$", ln, re.IGNORECASE):
                for j in range(i + 1, min(i + 6, len(lines))):
                    cand = lines[j].strip()
                    up = cand.upper()

                    # reject obvious non-name lines
                    if any(w in up for w in bad_name_words):
                        continue
                    if re.search(r"\d", cand):  # names usually no digits
                        continue
                    if len(cand) < 3:
                        continue
                    # looks like person name
                    if re.search(r"^[A-Za-z][A-Za-z\s\.]+$", cand):
                        customer_name = cand.title()
                        break
                break

        # 3) order id: prefer bottom alphanumeric token like abc123
        # Search from bottom upward and skip known noise tokens
        noise = {
            "DELHIVERY",
            "PRE",
            "PAID",
            "SURFACE",
            "MUMBAI",
            "MAHARASHTRA",
            "INDIA",
            "SELLER",
            "ADDRESS",
            "PRODUCT",
            "PRICE",
            "TOTAL",
            "DATE",
            "SHIP",
            "TO",
            "PIN",
            "MMB",
            "CHI",
        }

        for ln in reversed(lines[-20:]):  # only bottom section
            # candidate tokens
            toks = re.findall(r"\b([A-Za-z][A-Za-z0-9\-_]{2,})\b", ln)
            for tk in toks:
                up = tk.upper()

                if up in noise:
                    continue
                if "_" in tk:  # avoid address-like Mumbai_Parel1_D
                    continue
                # must contain both letters and digits
                if not (re.search(r"[A-Za-z]", tk) and re.search(r"\d", tk)):
                    continue
                # avoid too long address-ish tokens
                if len(tk) > 20:
                    continue

                order_id = tk
                break
            if order_id:
                break

        return {
            "courier": "delhivery",
            "customer_name": customer_name,
            "order_id": order_id,
            "shipment_id": shipment_id,
        }

    def _parse_shiprocket(self, text: str) -> dict:
        lines = self._normalize_lines(text)

        customer_name = ""
        shipment_id = ""
        order_id = ""

        # -------------------------
        # customer name from Ship To block
        # -------------------------
        for i, ln in enumerate(lines):
            if re.search(r"^Ship\s*To\s*:?\s*$", ln, re.IGNORECASE):
                for j in range(i + 1, min(i + 6, len(lines))):
                    cand = lines[j].strip()
                    if re.search(
                        r"(Mumbai|India|Dimensions|Payment|Order Total|Weight|AWB|EWaybill|Routing|PIN|GSTIN)",
                        cand,
                        re.IGNORECASE,
                    ):
                        continue
                    if re.search(r"\d", cand):
                        continue
                    if re.search(r"^[A-Za-z][A-Za-z\s\.]+$", cand):
                        customer_name = cand.title()
                        break
                break

        # -------------------------
        # shipment / AWB
        # -------------------------
        m = re.search(r"\bAWB\s*[:#]?\s*([A-Za-z0-9\-]{8,})\b", text, re.IGNORECASE)
        if m:
            shipment_id = m.group(1).strip()

        # -------------------------
        # order id (strict priority)
        # -------------------------

        # 1) explicit "Order# : 9167035350"
        m = re.search(r"\bOrder\s*#\s*:\s*([A-Za-z0-9\-_\/]+)\b", text, re.IGNORECASE)
        if m:
            order_id = m.group(1).strip()

        # 2) explicit "Order ID: xxx"
        if not order_id:
            m = re.search(
                r"\bOrder\s*ID\s*[:#]?\s*([A-Za-z0-9\-_\/]+)\b", text, re.IGNORECASE
            )
            if m:
                order_id = m.group(1).strip()

        # 3) fallback from item row (left-most token like abc123)
        if not order_id:
            noise = {
                "TOTAL",
                "ITEM",
                "SKU",
                "QTY",
                "PRICE",
                "HSN",
                "TAXABLE",
                "VALUE",
                "ORDER",
                "DATE",
                "INVOICE",
                "GSTIN",
                "PLATFORM",
                "DISCOUNT",
                "COLLECTABLE",
                "AMOUNT",
            }
            for ln in lines:
                # usually product table lines have multiple columns; first token may be order ref
                toks = re.findall(r"\b([A-Za-z][A-Za-z0-9\-_]{2,})\b", ln)
                if not toks:
                    continue
                first = toks[0]
                up = first.upper()
                if up in noise:
                    continue
                if re.search(r"[A-Za-z]", first) and re.search(r"\d", first):
                    order_id = first
                    break

        return {
            "courier": "shiprocket",
            "customer_name": customer_name,
            "order_id": order_id,
            "shipment_id": shipment_id,
        }


import io
import json
import re
import base64
from typing import Dict, Any, List

import pdfplumber
import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt


def _build_http_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=["POST"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


@method_decorator(csrf_exempt, name="dispatch")
class ParseLabelWithLLMView(View):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hf_api_key = getattr(
            settings,
            "HUGGINGFACE_API_KEY",
            None,
        )

        if not self.hf_api_key:
            raise ValueError("HUGGINGFACE_API_KEY missing in Django settings")

        self.hf_model = "moonshotai/Kimi-K3:fireworks-ai"

        self.hf_url = "https://router.huggingface.co/v1/chat/completions"

        # self.http = _build_http_session()

    def post(self, request, *args, **kwargs):
        try:
            f = request.FILES.get("file")
            if not f:
                return JsonResponse({"ok": False, "error": "file is required"}, status=400)
            if not f.name.lower().endswith(".pdf"):
                return JsonResponse({"ok": False, "error": "only pdf supported"}, status=400)

            # reset pointer before read
            f.seek(0)
            pdf_bytes = f.read()

            if not pdf_bytes:
                return JsonResponse({"ok": False, "error": "empty pdf"}, status=400)

            # if you need to read again later, do f.seek(0) again before next read
            reader = PdfReader(io.BytesIO(pdf_bytes))
            meta = reader.metadata or {}

            data = {
                "title": str(meta.get("/Title", "") or ""),
                "author": str(meta.get("/Author", "") or ""),
                "creator": str(meta.get("/Creator", "") or ""),
                "producer": str(meta.get("/Producer", "") or ""),
                "creation_date": str(meta.get("/CreationDate", "") or ""),
                "mod_date": str(meta.get("/ModDate", "") or ""),
                "pages": len(reader.pages),
            }

            print("PDF Metadata:", data)
            return JsonResponse({"ok": True, "filename": f.name, "metadata": data}, status=200)

        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)

    # def post(self, request, *args, **kwargs):

    #     try:
    #         f = request.FILES.get("file")
    #         if not f:
    #             return JsonResponse({"ok": False, "error": "file is required"}, status=400)
    #         if not f.name.lower().endswith(".pdf"):
    #             return JsonResponse({"ok": False, "error": "only pdf supported"}, status=400)

    #         pdf_bytes = f.read()
    #         if not pdf_bytes:
    #             return JsonResponse({"ok": False, "error": "empty pdf"}, status=400)

    #         reader = PdfReader(io.BytesIO(pdf_bytes))
    #         meta = reader.metadata or {}

    #         data = {
    #             "title": str(meta.get("/Title", "") or ""),
    #             "author": str(meta.get("/Author", "") or ""),
    #             "creator": str(meta.get("/Creator", "") or ""),
    #             "producer": str(meta.get("/Producer", "") or ""),
    #             "creation_date": str(meta.get("/CreationDate", "") or ""),
    #             "mod_date": str(meta.get("/ModDate", "") or ""),
    #             "pages": len(reader.pages),
    #         }

    #         # print in server logs too
    #         print("PDF Metadata:", data)

    #         uploaded = request.FILES.get("file")

    #         if not uploaded:

    #             return JsonResponse(
    #                 {
    #                     "ok": False,
    #                     "error": "file is required",
    #                 },
    #                 status=400,
    #             )

    #         filename = uploaded.name.lower()

    #         if not filename.endswith(".pdf"):

    #             return JsonResponse(
    #                 {
    #                     "ok": False,
    #                     "error": "only pdf supported",
    #                 },
    #                 status=400,
    #             )
    #         pdf_bytes = uploaded.read()

    #         if not pdf_bytes:

    #             return JsonResponse(
    #                 {
    #                     "ok": False,
    #                     "error": "empty pdf",
    #                 },
    #                 status=400,
    #             )

            # extracted_text = self._extract_pdf_text(pdf_bytes)

            # page_images_b64 = self._pdf_pages_to_base64_images(
            #     pdf_bytes,
            #     max_pages=3,
            #     dpi=200,
            # )

            # if not page_images_b64:

            #     return JsonResponse(
            #         {
            #             "ok": False,
            #             "error": ("could not render pdf pages"),
            #         },
            #         status=422,
            #     )

            # parsed = self._hf_extract_multimodal(
            #     page_images_b64=page_images_b64,
            #     text_fallback=extracted_text,
            # )

            # parsed = self._normalize_result(parsed)

            # return JsonResponse(
            #     {
            #         "ok": True,
            #         "filename": uploaded.name,
            #         "parsed": parsed,
            #         "raw_text_preview": (extracted_text[:1000]),
            #         "pages_sent": len(page_images_b64),
            #     },
            #     status=200,
            # )

        except requests.exceptions.Timeout:

            return JsonResponse(
                {
                    "ok": False,
                    "error": ("HuggingFace request timed out"),
                },
                status=504,
            )
        except requests.exceptions.RequestException as e:

            return JsonResponse(
                {
                    "ok": False,
                    "error": (f"HuggingFace request failed: {str(e)}"),
                },
                status=502,
            )

        except Exception as e:

            return JsonResponse(
                {
                    "ok": False,
                    "error": str(e),
                },
                status=500,
            )

    def _extract_pdf_text(
        self,
        pdf_bytes: bytes,
    ) -> str:

        texts: List[str] = []

        try:

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:

                for page in pdf.pages:

                    try:

                        text = page.extract_text() or ""

                        if text.strip():
                            texts.append(text)

                    except Exception:
                        continue

        except Exception:
            return ""

        return "\n".join(texts)

    def _pdf_pages_to_base64_images(
        self,
        pdf_bytes: bytes,
        max_pages: int = 3,
        dpi: int = 200,
    ) -> List[str]:

        images_b64: List[str] = []

        try:

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:

                total_pages = min(
                    len(pdf.pages),
                    max_pages,
                )

                for index in range(total_pages):

                    page = pdf.pages[index]

                    try:

                        # pdfplumber uses pdf2image/ImageMagick
                        page_image = page.to_image(resolution=dpi)

                        pil_img = page_image.original

                        buffer = io.BytesIO()

                        pil_img.save(
                            buffer,
                            format="PNG",
                            optimize=True,
                        )

                        image_bytes = buffer.getvalue()

                        encoded = base64.b64encode(image_bytes).decode("utf-8")

                        images_b64.append(encoded)

                    except Exception:
                        continue

        except Exception:
            return []

        return images_b64

    def _hf_extract_multimodal(
        self,
        page_images_b64: List[str],
        text_fallback: str,
    ) -> Dict[str, Any]:

        instruction = """
        You are a shipping-label information extraction system.

        Look carefully at the provided shipping-label image(s).

        Extract exactly these fields:

        - customer_name
        - awb_no
        - order_no
        - courier_name

        Return ONLY one JSON object.

        Required JSON format:

        {
        "customer_name": "",
        "awb_no": "",
        "order_no": "",
        "courier_name": ""
        }

        Rules:

        1. customer_name:
        - Must be the receiver/customer.
        - Look for "Ship To", "Deliver To", "Receiver", etc.
        - Never use the sender/shipper/company as customer_name.

        2. awb_no:
        - Find the AWB, airway bill, tracking number,
            shipment number or shipping ID.
        - Preserve every digit exactly.
        - Do not invent or modify digits.

        3. order_no:
        - Find the merchant order number/order ID.
        - Preserve it exactly.
        - Do not confuse it with AWB/tracking number.

        4. courier_name:
        - Identify the courier from visible text,
            logo, branding or label layout.
        - Examples include Delhivery, Blue Dart,
            Xpressbees, Ecom Express, DTDC, etc.
        - If uncertain, return an empty string.

        5. If a field cannot be confidently identified,
        return an empty string.

        6. Do not explain your reasoning.

        7. Do not return markdown.

        8. Do not return ```json.

        9. Return ONLY the JSON object.
        """.strip()

        content_blocks = [
            {
                "type": "text",
                "text": instruction,
            }
        ]

        for image_b64 in page_images_b64:

            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": ("data:image/png;base64," + image_b64)},
                }
            )

        if text_fallback.strip():

            # Keep this reasonably small.
            fallback_text = text_fallback[:12000]

            content_blocks.append(
                {
                    "type": "text",
                    "text": (
                        "\n\n"
                        "Supplementary text extracted "
                        "from the PDF. Use it only as "
                        "additional context and prioritize "
                        "the actual page image:\n\n" + fallback_text
                    ),
                }
            )

        headers = {
            "Authorization": (f"Bearer {self.hf_api_key}"),
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.hf_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict shipping-label " "JSON extraction API."
                    ),
                },
                {
                    "role": "user",
                    "content": content_blocks,
                },
            ],
            "temperature": 0,
            "max_tokens": 300,
        }

        print(
            "Calling Hugging Face model:",
            self.hf_model,
        )
        response = self.http.post(
            self.hf_url,
            headers=headers,
            json=payload,
            timeout=120,
        )

        if response.status_code != 200:

            try:
                error = response.json()
            except Exception:
                error = response.text

            raise Exception(f"HF API error " f"{response.status_code}: {error}")

        try:

            data = response.json()

        except json.JSONDecodeError:

            raise Exception(
                "HuggingFace returned invalid JSON: " + response.text[:1000]
            )

        print("HF RESPONSE:")

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
        )

        try:

            message = data["choices"][0]["message"]

        except (
            KeyError,
            IndexError,
            TypeError,
        ):

            raise Exception("Unexpected HF response format: " + json.dumps(data)[:2000])

        out_text = message.get(
            "content",
            "",
        )

        if isinstance(
            out_text,
            list,
        ):

            parts = []

            for item in out_text:

                if isinstance(
                    item,
                    dict,
                ):

                    parts.append(
                        str(
                            item.get(
                                "text",
                                "",
                            )
                        )
                    )

                else:

                    parts.append(str(item))

            out_text = "".join(parts)

        out_text = str(out_text).strip()

        if not out_text:

            reasoning = message.get(
                "reasoning_content",
                "",
            )

            if reasoning:

                raise Exception(
                    "Model returned reasoning but "
                    "no final answer: " + str(reasoning)[:1000]
                )

            raise Exception("Model returned empty content: " + json.dumps(data)[:2000])

        return self._parse_llm_json(out_text)

    def _parse_llm_json(
        self,
        text: str,
    ) -> Dict[str, Any]:

        text = (text or "").strip()

        try:

            result = json.loads(text)

            if isinstance(
                result,
                dict,
            ):
                return result

        except json.JSONDecodeError:
            pass

        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        ).strip()

        try:

            result = json.loads(cleaned)

            if isinstance(
                result,
                dict,
            ):
                return result

        except json.JSONDecodeError:
            pass
        start = cleaned.find("{")

        if start != -1:

            depth = 0
            in_string = False
            escaped = False

            for i in range(
                start,
                len(cleaned),
            ):

                char = cleaned[i]

                # Handle JSON strings
                if char == '"' and not escaped:
                    in_string = not in_string

                if char == "\\" and not escaped:
                    escaped = True
                else:
                    escaped = False

                if in_string:
                    continue

                if char == "{":
                    depth += 1

                elif char == "}":

                    depth -= 1

                    if depth == 0:

                        candidate = cleaned[start : i + 1]

                        try:

                            result = json.loads(candidate)

                            if isinstance(
                                result,
                                dict,
                            ):
                                return result

                        except json.JSONDecodeError:
                            pass

                        break

        raise Exception("Model did not return valid JSON: " + text[:1500])

    def _normalize_result(
        self,
        parsed: Dict[str, Any],
    ) -> Dict[str, str]:

        customer_name = str(
            parsed.get(
                "customer_name",
                "",
            )
            or ""
        ).strip()

        customer_name = re.sub(
            r"\s+",
            " ",
            customer_name,
        )

        awb_no = str(
            parsed.get(
                "awb_no",
                "",
            )
            or ""
        ).strip()

        awb_no = re.sub(
            r"[^\w\-/]",
            "",
            awb_no,
        )
        order_no = str(
            parsed.get(
                "order_no",
                "",
            )
            or ""
        ).strip()

        order_no = re.sub(
            r"[^\w\-/]",
            "",
            order_no,
        )

        courier_name = str(
            parsed.get(
                "courier_name",
                "",
            )
            or ""
        ).strip()

        courier_name = re.sub(
            r"\s+",
            " ",
            courier_name,
        )

        return {
            "customer_name": customer_name,
            "awb_no": awb_no,
            "order_no": order_no,
            "courier_name": courier_name,
        }
