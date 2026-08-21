import hashlib
import io

from pypdf import PdfReader
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from payments.models.merchantinfo import MerchantInfo


class PDFUploadRequestSerializer(serializers.Serializer):
	file = serializers.FileField(required=True)


class PDFUploadOpenAPIView(GenericAPIView):


	permission_classes = [AllowAny]
	authentication_classes = []
	parser_classes = [MultiPartParser, FormParser]
	serializer_class = PDFUploadRequestSerializer

	def _extract_authorization_key(self, request):
		auth_value = (request.headers.get("Authorization") or "").strip()
		if not auth_value:
			return ""

		parts = auth_value.split(" ", 1)
		if len(parts) == 2 and parts[0].lower() == "bearer":
			return parts[1].strip()

		return auth_value

	def post(self, request, *args, **kwargs):
		authorization_key = self._extract_authorization_key(request)
		if not authorization_key:
			return Response(
				{"ok": False, "error": "Authorization key is required"},
				status=status.HTTP_401_UNAUTHORIZED,
			)

		merchant_exists = MerchantInfo.objects.filter(
			merchant_key=authorization_key
		).exists()
		if not merchant_exists:
			return Response(
				{"ok": False, "error": "Invalid merchant key"},
				status=status.HTTP_401_UNAUTHORIZED,
			)

		serializer = self.get_serializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		file_obj = serializer.validated_data["file"]
		filename = file_obj.name or "uploaded.pdf"

		if not filename.lower().endswith(".pdf"):
			return Response(
				{"ok": False, "error": "only PDF file allowed"},
				status=status.HTTP_400_BAD_REQUEST,
			)

		pdf_bytes = file_obj.read()
		if not pdf_bytes:
			return Response(
				{"ok": False, "error": "empty PDF file"},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			reader = PdfReader(io.BytesIO(pdf_bytes))
			pages = len(reader.pages)
		except Exception as exc:
			return Response(
				{"ok": False, "error": f"invalid PDF: {str(exc)}"},
				status=status.HTTP_400_BAD_REQUEST,
			)

		return Response(
			{
				"ok": True,
				"message": "PDF accepted",
				"filename": filename,
				"content_type": file_obj.content_type,
				"size_bytes": len(pdf_bytes),
				"pages": pages,
				"sha256": hashlib.sha256(pdf_bytes).hexdigest(),
			},
			status=status.HTTP_200_OK,
		)


class UpdateAPIKey(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        new_api_key = request.data.get("new_api_key")
        if not new_api_key:
            return Response(
                {"ok": False, "error": "new_api_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        merchant_info = MerchantInfo.objects.first()
        if not merchant_info:
            return Response(
                {"ok": False, "error": "Merchant info not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        merchant_info.merchant_key = new_api_key
        merchant_info.save()

        return Response(
            {"ok": True, "message": "API key updated successfully"},
            status=status.HTTP_200_OK,
        )