import random
from rest_framework.views import APIView, Response, status
from payments.models.merchantinfo import MerchantInfo

class CreateMerchant(APIView):
    def post(self, request):
        self.merchant_name = request.data.get('merchant_name')
        self.merchant_email = request.data.get('merchant_email')
        self.merchant_phone = request.data.get('merchant_phone')
        self.merchant_address = request.data.get('merchant_address')
        return self.create_merchant()

    def create_merchant(self):
        try:
            merchant_info = MerchantInfo(
                merchant_name=self.merchant_name,
                merchant_email=self.merchant_email,
                merchant_phone=self.merchant_phone,
                merchant_address=self.merchant_address,
                merchant_key = self.generate_key(),
                merchant_salt = self.generate_key()
            )
            merchant_info.save()
            return Response(
                {
                    "message": "Merchant created successfully.", 
                    "merchant_id": merchant_info.id, 
                    "merchant_key": merchant_info.merchant_key, 
                    "merchant_salt": merchant_info.merchant_salt
                }, status=status.HTTP_201_CREATED
            )
        except Exception as e:
            raise ValueError(f"Error creating merchant: {str(e)}")

    def generate_key(self):
        return str(random.randint(10000000, 99999999))