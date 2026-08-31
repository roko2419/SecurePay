"""Cross-merchant read views for the admin panel: every order and every
enquiry in the system, regardless of which merchant they belong to.

The merchant-facing views (payments.api.v1.generate_order.ShipmentListView)
scope everything to the logged-in merchant's own orders; these views
deliberately don't, since the whole point of the admin panel is to see
across merchants.
"""

from django.conf import settings
from django.db.models import Q

from rest_framework.views import Response

from adminpanel.permissions import AdminAPIView
from payments.models.orderinfo import OrderInfo
from payments.models.enquirydata import EnquiryData, EnquiryNote


class AdminOrderListView(AdminAPIView):
    """Paginated, searchable list of every order across all merchants."""

    def get(self, request):
        # limit/page/q all come from query params and are best-effort parsed —
        # bad input just falls back to sane defaults rather than erroring.
        try:
            limit = min(int(request.GET.get("limit", 25)), 200)
        except ValueError:
            limit = 25
        try:
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            page = 1
        q = (request.GET.get("q") or "").strip().lower()
        merchant_id = request.GET.get("merchant_id")
        status_filter = request.GET.get("status")

        qs = OrderInfo.objects.select_related(
            "merchant", "customer_info", "shipment_id", "enquiry"
        ).order_by("-order_date")

        if merchant_id:
            qs = qs.filter(merchant_id=merchant_id)
        if status_filter:
            qs = qs.filter(order_status__iexact=status_filter)

        # .values(...) flattens related fields (merchant__merchant_name, etc.)
        # straight into dicts the frontend can render without extra joins.
        rows = qs.values(
            "id",
            "merchant_order_id",
            "pa_order_id",
            "pa_payment_id",
            "order_amount",
            "order_currency",
            "order_status",
            "order_date",
            "payment_provider",
            "merchant_id",
            "merchant__merchant_name",
            "merchant__merchant_email",
            "customer_info__customer_name",
            "customer_info__customer_email",
            "customer_info__customer_phone",
            "customer_info__customer_address",
            "shipment_id__awb",
            "shipment_id__courier",
            "shipment_id__status",
            "enquiry_id",
            "enquiry__enquiry_id",
            "enquiry__status",
        )

        # Free-text search is done in Python rather than the DB because it
        # spans multiple unrelated columns (order id, customer, merchant) —
        # simplest thing that works at this data volume.
        if q:
            rows = [
                r
                for r in rows
                if q
                in " ".join(
                    str(v) for v in [
                        r.get("merchant_order_id"),
                        r.get("pa_order_id"),
                        r.get("customer_info__customer_name"),
                        r.get("customer_info__customer_email"),
                        r.get("customer_info__customer_phone"),
                        r.get("merchant__merchant_name"),
                    ] if v
                ).lower()
            ]
        else:
            rows = list(rows)

        total = len(rows)
        total_pages = max(1, (total + limit - 1) // limit)
        start = (page - 1) * limit
        end = start + limit

        return Response(
            {
                "results": rows[start:end],
                "page": page,
                "total_pages": total_pages,
                "total": total,
            }
        )


class AdminEnquiryListView(AdminAPIView):
    """Paginated, searchable list of every customer enquiry, enriched with
    the order/customer/shipment/notes/resolution context an admin needs to
    act on it without opening several other screens."""

    def get(self, request):
        try:
            limit = min(int(request.GET.get("limit", 25)), 200)
        except ValueError:
            limit = 25
        try:
            page = max(int(request.GET.get("page", 1)), 1)
        except ValueError:
            page = 1
        q = (request.GET.get("q") or "").strip().lower()
        status_filter = request.GET.get("status")

        qs = EnquiryData.objects.all().order_by("-created_at")
        if status_filter:
            qs = qs.filter(status__iexact=status_filter)

        enquiries = list(
            qs.values(
                "id",
                "enquiry_id",
                "order_id",
                "enquiry_text",
                "receipt_status",
                "someone_else_received",
                "agent_contacted",
                "otp_shared",
                "unboxing_evidence",
                "evidence_file",
                "status",
                "created_at",
                "updated_at",
                "resolution_status",
                "resolution_reason",
                "resolved_by__username",
                "resolved_at",
            )
        )

        # NOTE: EnquiryData.order_id is a free-text field the enquiry form
        # captures from the customer — in practice it holds the payment
        # aggregator's order id (pa_order_id), not our merchant_order_id.
        # We match against both so enquiries resolve to an order either way.
        order_ids = [e["order_id"] for e in enquiries if e["order_id"]]
        matched_orders = list(
            OrderInfo.objects.filter(
                Q(pa_order_id__in=order_ids) | Q(merchant_order_id__in=order_ids)
            )
            .select_related("merchant", "customer_info", "shipment_id")
            .values(
                "merchant_order_id",
                "pa_order_id",
                "order_amount",
                "order_currency",
                "order_status",
                "merchant__merchant_name",
                "customer_info__customer_name",
                "customer_info__customer_email",
                "customer_info__customer_phone",
                "shipment_id__awb",
                "shipment_id__courier",
                "shipment_id__status",
            )
        )
        # Index by both id styles so the lookup below is a single dict hit
        # regardless of which one a given enquiry happens to reference.
        orders_by_order_id = {}
        for o in matched_orders:
            if o["pa_order_id"]:
                orders_by_order_id[o["pa_order_id"]] = o
            orders_by_order_id[o["merchant_order_id"]] = o

        # Pull just enough from EnquiryNote to show a preview + count in the
        # list view; the full note history is fetched separately per-enquiry
        # when the admin opens the notes modal (AdminEnquiryNoteListView).
        enquiry_ids = [e["id"] for e in enquiries]
        notes_count_by_enquiry = {}
        latest_note_by_enquiry = {}
        for note in (
            EnquiryNote.objects.filter(enquiry_id__in=enquiry_ids)
            .select_related("created_by")
            .order_by("enquiry_id", "-created_at")
        ):
            notes_count_by_enquiry[note.enquiry_id] = notes_count_by_enquiry.get(note.enquiry_id, 0) + 1
            if note.enquiry_id not in latest_note_by_enquiry:
                latest_note_by_enquiry[note.enquiry_id] = {
                    "id": note.id,
                    "note": note.note,
                    "created_by": note.created_by.username if note.created_by else None,
                    "created_at": note.created_at,
                }

        for e in enquiries:
            # Swap the raw stored file path for a browser-openable absolute URL.
            evidence_path = e.pop("evidence_file", None)
            if evidence_path:
                e["evidence_url"] = request.build_absolute_uri(f"{settings.MEDIA_URL}{evidence_path}")
            else:
                e["evidence_url"] = None

            order = orders_by_order_id.get(e["order_id"])
            e["order_amount"] = order.get("order_amount") if order else None
            e["order_currency"] = order.get("order_currency") if order else None
            e["order_status"] = order.get("order_status") if order else None
            e["merchant_name"] = order.get("merchant__merchant_name") if order else None
            e["customer_name"] = order.get("customer_info__customer_name") if order else None
            e["customer_email"] = order.get("customer_info__customer_email") if order else None
            e["customer_phone"] = order.get("customer_info__customer_phone") if order else None
            e["shipment_awb"] = order.get("shipment_id__awb") if order else None
            e["shipment_courier"] = order.get("shipment_id__courier") if order else None
            e["shipment_status"] = order.get("shipment_id__status") if order else None

            e["notes_count"] = notes_count_by_enquiry.get(e["id"], 0)
            e["latest_note"] = latest_note_by_enquiry.get(e["id"])

        if q:
            enquiries = [
                e
                for e in enquiries
                if q
                in " ".join(
                    str(v) for v in [
                        e.get("enquiry_id"),
                        e.get("order_id"),
                        e.get("customer_name"),
                        e.get("customer_email"),
                        e.get("merchant_name"),
                    ] if v
                ).lower()
            ]

        total = len(enquiries)
        total_pages = max(1, (total + limit - 1) // limit)
        start = (page - 1) * limit
        end = start + limit

        return Response(
            {
                "results": enquiries[start:end],
                "page": page,
                "total_pages": total_pages,
                "total": total,
            }
        )
