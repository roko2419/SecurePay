from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from payments.models import EnquiryData  # Assuming the model is named Shipment

class SubmitEnquiry(APIView):
    def post(self, request):
        order_id = request.data.get('order_id')
        enquiry_text = request.data.get('enquiry_msg')

        if not order_id or not enquiry_text:
            return Response({"error": "Missing required fields."}, status=status.HTTP_400_BAD_REQUEST)

        # Create a new EnquiryData instance
        enquiry = EnquiryData.objects.create(
            enquiry_id=f"ENQ{EnquiryData.objects.count() + 1}",
            order_id=order_id,
            enquiry_text=enquiry_text
        )

        return Response({"message": "Enquiry submitted successfully.", "enquiry_id": enquiry.enquiry_id}, status=status.HTTP_201_CREATED)