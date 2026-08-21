
import os
import tempfile

from rest_framework.views import APIView
from rest_framework.response import Response
from .label_validator import validate_label

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
            print(f"Validation result: {result.to_dict()}")  # Debugging line
            return Response(
                {
                    'is_valid': result.is_authentic,
                    'result': result.to_dict(),
                }
            )
        except Exception as exc:
            return Response({'error': str(exc)}, status=400)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)