from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from payments.models import EnquiryData
from tracking.signing import verify_order_signature

VALID_RECEIPT_STATUSES = {choice for choice, _ in EnquiryData.RECEIPT_STATUS_CHOICES}


def _parse_bool(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('true', '1', 'yes')


class SubmitEnquiry(APIView):
    def post(self, request):
        order_id = request.data.get('order_id')
        signature = request.data.get('sig')
        enquiry_text = request.data.get('enquiry_msg')
        receipt_status = request.data.get('receipt_status')

        if not order_id or not enquiry_text or not receipt_status:
            return Response({"error": "Missing required fields."}, status=status.HTTP_400_BAD_REQUEST)

        if not verify_order_signature(order_id, signature):
            return Response({"error": "Invalid or tampered order link."}, status=status.HTTP_403_FORBIDDEN)

        if receipt_status not in VALID_RECEIPT_STATUSES:
            return Response({"error": "Invalid receipt_status."}, status=status.HTTP_400_BAD_REQUEST)

        enquiry = EnquiryData.objects.create(
            enquiry_id=f"ENQ{EnquiryData.objects.count() + 1}",
            order_id=order_id,
            enquiry_text=enquiry_text,
            receipt_status=receipt_status,
            someone_else_received=_parse_bool(request.data.get('someone_else_received')),
            agent_contacted=_parse_bool(request.data.get('agent_contacted')),
            otp_shared=_parse_bool(request.data.get('otp_shared')),
            unboxing_evidence=_parse_bool(request.data.get('unboxing_evidence')),
            evidence_file=request.FILES.get('evidence_file'),
        )

        return Response({"message": "Enquiry submitted successfully.", "enquiry_id": enquiry.enquiry_id}, status=status.HTTP_201_CREATED)
