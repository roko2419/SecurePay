from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import Response, status

from adminpanel.permissions import AdminAPIView
from payments.models.enquirydata import EnquiryData, EnquiryNote

VALID_RESOLUTION_STATUSES = {choice[0] for choice in EnquiryData.RESOLUTION_STATUS_CHOICES}


def _serialize_note(note):
    return {
        "id": note.id,
        "note": note.note,
        "created_by": note.created_by.username if note.created_by else None,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


class AdminEnquiryNoteListView(AdminAPIView):
    """GET: list all notes for an enquiry. POST: add a new note."""

    def get(self, request, enquiry_id):
        enquiry = get_object_or_404(EnquiryData, id=enquiry_id)
        notes = enquiry.notes.select_related("created_by").order_by("-created_at")
        return Response({"results": [_serialize_note(n) for n in notes]})

    def post(self, request, enquiry_id):
        enquiry = get_object_or_404(EnquiryData, id=enquiry_id)
        text = (request.data.get("note") or "").strip()
        if not text:
            return Response({"error": "note text is required."}, status=status.HTTP_400_BAD_REQUEST)

        note = EnquiryNote.objects.create(
            enquiry=enquiry,
            note=text,
            created_by=request.admin_user,
        )
        return Response(_serialize_note(note), status=status.HTTP_201_CREATED)


class AdminEnquiryNoteDetailView(AdminAPIView):
    """PATCH: edit an existing note's text. DELETE: remove a note."""

    def patch(self, request, enquiry_id, note_id):
        note = get_object_or_404(EnquiryNote, id=note_id, enquiry_id=enquiry_id)
        text = (request.data.get("note") or "").strip()
        if not text:
            return Response({"error": "note text is required."}, status=status.HTTP_400_BAD_REQUEST)

        note.note = text
        note.save(update_fields=["note", "updated_at"])
        return Response(_serialize_note(note))

    def delete(self, request, enquiry_id, note_id):
        note = get_object_or_404(EnquiryNote, id=note_id, enquiry_id=enquiry_id)
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminEnquiryResolutionView(AdminAPIView):
    """PATCH: set the money-movement resolution for an enquiry, with a reason."""

    def patch(self, request, enquiry_id):
        enquiry = get_object_or_404(EnquiryData, id=enquiry_id)

        resolution_status = request.data.get("resolution_status")
        reason = (request.data.get("reason") or "").strip()

        if resolution_status not in VALID_RESOLUTION_STATUSES:
            return Response(
                {"error": f"resolution_status must be one of {sorted(VALID_RESOLUTION_STATUSES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if resolution_status != "unresolved" and not reason:
            return Response({"error": "reason is required for this status."}, status=status.HTTP_400_BAD_REQUEST)

        enquiry.resolution_status = resolution_status
        enquiry.resolution_reason = reason or None
        enquiry.resolved_by = request.admin_user
        enquiry.resolved_at = timezone.now()

        if resolution_status != "unresolved":
            enquiry.status = "resolved"

        enquiry.save(
            update_fields=[
                "resolution_status",
                "resolution_reason",
                "resolved_by",
                "resolved_at",
                "status",
                "updated_at",
            ]
        )

        return Response(
            {
                "id": enquiry.id,
                "resolution_status": enquiry.resolution_status,
                "resolution_reason": enquiry.resolution_reason,
                "resolved_by": request.admin_user.username,
                "resolved_at": enquiry.resolved_at,
                "status": enquiry.status,
            }
        )
