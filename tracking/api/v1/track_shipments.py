import io
import csv

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from tracking.models.trackinginfo import Shipment
from tracking.signing import build_enquiry_link
from tracking.api.v1.notifs import send_whatsapp_text
from payments.models import OrderInfo
import json
import logging
import requests

logger = logging.getLogger(__name__)


def notify_customer_delivered(pa_order_id):
    """Send the customer a WhatsApp message with their signed order-enquiry link."""
    order_info = OrderInfo.objects.filter(pa_order_id=pa_order_id).select_related("customer_info").first()
    if not order_info or not order_info.customer_info or not order_info.customer_info.customer_phone:
        logger.warning("Skipping delivery notification: no customer phone for order %s", pa_order_id)
        return

    link = build_enquiry_link(settings.FRONTEND_ENQUIRY_URL, pa_order_id)
    message = (
        f"Your order {pa_order_id} has been marked as delivered. "
        f"If there's an issue with your order, let us know here: {link}"
    )

    try:
        send_whatsapp_text(order_info.customer_info.customer_phone, message, preview_url=True)
    except Exception:
        logger.exception("Failed to send delivery WhatsApp notification for order %s", pa_order_id)


class CreateShipment(View):

    def post(self, request):
        # Logic to create a shipment
        request_data = json.loads(request.body.decode('utf-8'))
        try:
            shipment = Shipment.objects.create(
                courier=request_data.get('courier'),
                awb=request_data.get('awb'),
                pa_order_id=request_data.get('secureupi_order_id')
            )
            order_info = OrderInfo.objects.filter(pa_order_id=shipment.pa_order_id).first()
            order_info.shipment_id = shipment
            order_info.save()
            push_to_shipsagar(request_data.get('awb'), request_data.get('courier'), order_info.pa_order_id, order_info.customer_info.customer_name, order_info.customer_info.customer_email, order_info.customer_info.customer_phone)
            print(f"Shipment created with AWB: {shipment.awb}, Courier: {shipment.courier}, PA Order ID: {shipment.pa_order_id}")
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
        return JsonResponse({'awb': shipment.awb})

    def get(self, request, awb=None):
        """
        GET may be called as:
         - /tracking/track_shipment/?awb=AWB123
         - /tracking/track_shipment/AWB123/
        """
        # accept awb from path param first, then from query string
        if not awb:
            awb = request.GET.get('awb')

        if not awb:
            return JsonResponse({'error': 'AWB is required either as path param or ?awb='}, status=400)

        try:
            shipment = Shipment.objects.get(awb=awb)
            shipment_data = {
                'awb': shipment.awb,
                'courier': shipment.courier,
                'pa_order_id': shipment.pa_order_id,
                'status': shipment.status,
                'history': shipment.history,
                'created_at': shipment.created_at.isoformat()
            }
            print(f"Retrieved shipment: {shipment_data}")
        except Shipment.DoesNotExist:
            return JsonResponse({'error': 'Shipment not found'}, status=404)

        return JsonResponse(shipment_data)

# tracking/views.py
import uuid
from django.http import JsonResponse
from django.views import View
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from tracking.models.trackinginfo import Shipment

@method_decorator(csrf_exempt, name="dispatch")   # remove this in production
class UpdateShipment(View):
    """
    POST /tracking/track_shipment/<awb>/delivered
    (also supports GET for convenience)
    """

    def post(self, request, awb=None, *args, **kwargs):
        return self._mark_delivered(request, awb)

    def get(self, request, awb=None, *args, **kwargs):
        # WARNING: GET should not be used to change state in real apps,
        # this is provided only for convenience/testing.
        return self._mark_delivered(request, awb)

    def _mark_delivered(self, request, awb):
        # accept awb from path or querystring
        if not awb:
            awb = request.GET.get("awb")

        if not awb:
            return JsonResponse({"ok": False, "error": "AWB is required (path param or ?awb=)"}, status=400)

        try:
            with transaction.atomic():
                shipment = Shipment.objects.select_for_update().get(awb=awb)
                if shipment.status == "DELIVERED":
                    return JsonResponse({"ok": True, "msg": "already delivered", "awb": awb, "status": shipment.status})

                shipment.status = "DELIVERED"
                # add history entry if model supports it
                try:
                    shipment.add_history("DELIVERED", note="Marked as delivered via API")
                except Exception:
                    # fallback if no helper method
                    hist = getattr(shipment, "history", []) or []
                    hist.append({"ts": str(uuid.uuid4()), "status": "DELIVERED", "note": "Marked delivered via API"})
                    try:
                        shipment.history = hist
                    except Exception:
                        pass

                shipment.save()
        except Shipment.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Shipment not found"}, status=404)
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)

        notify_customer_delivered(shipment.pa_order_id)

        return JsonResponse({"ok": True, "awb": awb, "status": "DELIVERED"})

class CreateBulkShipment(View):

    def post(self, request):
        """
        POST /tracking/create_shipments_bulk/
        Body: JSON array of shipments, each with 'courier', 'awb', 'secureupi_order_id'
        """
        uploaded_file = request.FILES.get("file")

        if not uploaded_file:
            return JsonResponse(
                {
                    "error": "CSV file is required"
                },
                status=400
            )

        # --------------------------------------------------
        # Validate file
        # --------------------------------------------------

        if not uploaded_file.name.lower().endswith(".csv"):
            return JsonResponse(
                {
                    "error": "Only CSV files are allowed"
                },
                status=400
            )

        try:

            content = uploaded_file.read().decode("utf-8-sig")

        except UnicodeDecodeError:

            return JsonResponse(
                {
                    "error": "CSV must be UTF-8 encoded"
                },
                status=400
            )

        # --------------------------------------------------
        # Parse CSV
        # --------------------------------------------------

        try:

            reader = csv.DictReader(
                io.StringIO(content)
            )

            if not reader.fieldnames:

                return JsonResponse(
                    {
                        "error": "CSV has no header"
                    },
                    status=400
                )

            # Normalize headers
            fieldnames = [
                field.strip().lower()
                for field in reader.fieldnames
            ]

            required_fields = {
                "secureupi_order_id",
                "awb",
                "courier"
            }

            missing = required_fields - set(fieldnames)

            if missing:

                return JsonResponse(
                    {
                        "error": "Missing CSV columns",
                        "missing": list(missing),
                        "required": [
                            "secureupi_order_id",
                            "awb",
                            "courier"
                        ]
                    },
                    status=400
                )

        except Exception as e:

            return JsonResponse(
                {
                    "error": f"Invalid CSV: {str(e)}"
                },
                status=400
            )

        # --------------------------------------------------
        # Process rows
        # --------------------------------------------------

        results = []

        success_count = 0
        failed_count = 0

        for row_number, row in enumerate(reader, start=2):

            # Normalize row keys
            normalized_row = {
                key.strip().lower(): (
                    value.strip()
                    if value
                    else ""
                )
                for key, value in row.items()
                if key
            }

            order_id = normalized_row.get(
                "secureupi_order_id",
                ""
            )

            awb = normalized_row.get(
                "awb",
                ""
            )

            courier = normalized_row.get(
                "courier",
                ""
            )

            # ----------------------------------------------
            # Validate row
            # ----------------------------------------------

            if not order_id:

                results.append({
                    "row": row_number,
                    "secureupi_order_id": "",
                    "success": False,
                    "error": "secureupi_order_id is required"
                })

                failed_count += 1
                continue

            if not courier:

                results.append({
                    "row": row_number,
                    "secureupi_order_id": order_id,
                    "success": False,
                    "error": "courier is required"
                })

                failed_count += 1
                continue

            # ----------------------------------------------
            # Create shipment
            # ----------------------------------------------

            try:

                result = Shipment.objects.create(
                    courier=courier,
                    awb=awb,
                    pa_order_id=order_id
                )
                order_info = OrderInfo.objects.filter(pa_order_id=result.pa_order_id).first()
                order_info.shipment_id = result
                order_info.save()
                print(f"Shipment created with AWB: {result.awb}, Courier: {result.courier}, PA Order ID: {result.pa_order_id}")
                push_to_shipsagar(awb, courier, order_info.pa_order_id, order_info.customer_info.customer_name, order_info.customer_info.customer_email, order_info.customer_info.customer_phone)
                results.append({
                    "row": row_number,
                    "secureupi_order_id": order_id,
                    "success": True,
                    "awb": awb,
                    "status": result.status
                })

                success_count += 1

            except Exception as e:

                results.append({
                    "row": row_number,
                    "secureupi_order_id": order_id,
                    "success": False,
                    "error": str(e)
                })

                failed_count += 1

        # --------------------------------------------------
        # Response
        # --------------------------------------------------

        return JsonResponse({
            "success": True,
            "total": success_count + failed_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        })

def push_to_shipsagar(awb, courier, order_number, customer_name, customer_email, customer_phone):
    """
    Placeholder function to push shipment data to external service (e.g., Shipsagar).
    In a real implementation, this would make an HTTP request to the external API.
    """
    url = 'http://app.shipsagar.com/api/Web/PushShipment'

    payload = {
      "Token": "0691F3D5-0B37-4520-A1DC-1DD4C151CC42",
      "ClientCode": "C1375",
      "CourierCode": courier,
      "TrackingNo": awb,
      "OrderNo": order_number,
      "CustomerName": customer_name,
      "EmailID": customer_email or 'random@gmail.com',
      "ShipmentType": "Train",
      "MobileNo": customer_phone,
      "CountryName": "India",
      "CompanyName": "XYZ Pvt Ltd",
    }
    response = requests.post(url, json=payload)
    print(f"Shipsagar response: {response.status_code} - {response.text}")
    print(f"Pushing shipment to Shipsagar: {payload}")
    return True

class TrackShipmentShipsagar(View):

    def get(self, request, awb=None):
        """
        GET /tracking/track_shipment/shipsagar/<awb>/
        """
        url = 'http://app.shipsagar.com/api/Web/TrackShipment'
        payload = {
            "Token":"0691F3D5-0B37-4520-A1DC-1DD4C151CC42",
            "ClientCode":"C1375",
            "TrackingNo":awb
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            response_data = response.json()
            shipment = Shipment.objects.filter(awb=awb).first()
            if not shipment:
                return JsonResponse({"error": "Shipment not found in local database"}, status=404)
            if response_data.get('status') != 'success':
                return JsonResponse({"error": "Failed to fetch shipment status from Shipsagar", "details": response_data}, status=400)
            tracking_details = json.loads(
                json.loads(response_data["trackingDetails"])
            )
            status = tracking_details.get("CurrentStatus", "")
            was_delivered = shipment.status.strip().lower() == "delivered"
            shipment.status = status
            shipment.save()

            if status.strip().lower() == "delivered" and not was_delivered:
                notify_customer_delivered(shipment.pa_order_id)
            return JsonResponse(status=200, data={
                "awb": shipment.awb,
                "secureupi_order_id": getattr(shipment, "pa_order_id", None) or getattr(shipment, "secureupi_order_id", None),
                "payment_id": getattr(shipment, "payment_id", None) or (getattr(shipment, "payment", None) and getattr(shipment.payment, "payment_id", None)),
                "courier": shipment.courier,
                "status": shipment.status,
                "history": shipment.history if hasattr(shipment, "history") else [],
                "order_status": getattr(shipment.secureupi_order, "status", None) if getattr(shipment, "secureupi_order", None) else None,
                "customer": {
                    "name": getattr(shipment.secureupi_order, "customer_name", None),
                    "phone": getattr(shipment.secureupi_order, "customer_phone", None),
                } if getattr(shipment, "secureupi_order", None) else None,
                "created_at": shipment.created_at.isoformat() if hasattr(shipment, "created_at") else None,
            })
        else:
            return JsonResponse({"error": "Failed to fetch shipment status from Shipsagar"}, status=response.status_code)