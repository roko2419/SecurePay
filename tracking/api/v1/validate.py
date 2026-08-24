
import os
import tempfile

from rest_framework.views import APIView
from rest_framework.response import Response
from .label_validator import validate_label
from .color_parser import extract_major_colors_from_pdf
from payments.models import OrderInfo
from tracking.models.trackinginfo import Shipment
import re


class PDFValidator(APIView):
    """
    API endpoint for validating PDF files.
    """

    def post(self, request):

        pdf_file = request.FILES.get('file')
        if not pdf_file:
            return Response({'error': 'No file provided'}, status=400)

        if not pdf_file.name.lower().endswith('.pdf'):
            return Response({'error': 'Only PDF files are allowed'}, status=400)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_pdf:
                for chunk in pdf_file.chunks():
                    temp_pdf.write(chunk)
                temp_path = temp_pdf.name

            result = validate_label(temp_path)
            delhivery_match = 0
            if not result.delivery_partner:
                color  = extract_major_colors_from_pdf(pdf_file)
                page_colors = color['all_pages']
                for page in page_colors:
                    for color in page["colors"]:
                        print(color['hex'])
                        if color['hex'] in ['#394058', '#53596e', '#474d64', '#646a7d', '#868b9a', '#767b8c', '#e82223', '#fcdfdf']:
                            delhivery_match += 1
            print(delhivery_match)
            partner = 'Unknown'
            self.from_color = False
            if delhivery_match > 6:
                partner = "Delhivery"
                self.from_color = True
            print(f"Validation result: {result.to_dict()}")  # Debugging line
            delivery_partner = result.delivery_partner if result.delivery_partner else partner
            order_id = self.get_order_id(delivery_partner, result.raw_text, result.barcodes)
            res = {
                'delivery_partner': delivery_partner,
                'awb': result.awb,
                'is_valid': result.is_authentic,
                'order_id': order_id
            }
            print('final result',res)
            try:
                shipment = Shipment.objects.get(awb=result.awb)
            except Shipment.DoesNotExist:
                shipment = Shipment(
                    awb=result.awb,
                    courier=delivery_partner
                )
            shipment.save()
            order = OrderInfo.objects.filter(merchant_order_id=order_id).first()
            order.shipment_id = shipment
            order.save()

            return Response(
                {
                    'delivery_partner': delivery_partner,
                    'awb': result.awb,
                    'is_valid': result.is_authentic,
                    'result': result.to_dict(),
                    'order_id': order_id
                }
            )
        except Exception as exc:
            print(exc)
            return Response({'error': str(exc)}, status=400)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def get_order_id(self, delivery_partner, raw_text, barcodes):
        if  "Delhivery" in delivery_partner:
            return barcodes[1] if self.from_color else barcodes[0]
        elif delivery_partner == "Xpressbees Surface":
            return barcodes[0]
        elif 'Blue Dart' in delivery_partner:
            match = re.search(r"Order#\s*:\s*(\d+)", raw_text, re.IGNORECASE)
            if match:
                return match.group(1)
        elif 'DTDC' in delivery_partner:
            return barcodes[1]
        elif 'SHADOWFAX' in delivery_partner:
            patterns = [
                r"Client Order Id\s*:\s*([A-Za-z0-9-]+)",
                r"Order#\s*:\s*(\d+)",
                r"Order\s*No\.?\s*[:#]?\s*([A-Za-z0-9-]+)",
            ]
            for pattern in patterns:
                match = re.search(pattern, raw_text, re.IGNORECASE)
                if match:
                    return match.group(1)

        return None