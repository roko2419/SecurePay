from django.contrib import admin

from tracking.models.whatsapp_log import WhatsAppMessageLog


@admin.register(WhatsAppMessageLog)
class WhatsAppMessageLogAdmin(admin.ModelAdmin):
    list_display = ("to_number", "purpose", "order_id", "status", "wa_message_id", "created_at")
    list_filter = ("status", "purpose")
    search_fields = ("to_number", "order_id", "wa_message_id", "message_body")
    readonly_fields = (
        "to_number",
        "purpose",
        "order_id",
        "message_body",
        "status",
        "error",
        "wa_id",
        "wa_message_id",
        "raw_response",
        "created_at",
        "updated_at",
    )
