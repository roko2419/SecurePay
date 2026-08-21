# utils/whatsapp.py
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_whatsapp_text(to_number: str, message: str, preview_url: bool = False):
    """
    Send WhatsApp text message using GetGabs service API.

    Args:
        to_number (str): Recipient phone number in full format, e.g. '919999999999'
        message (str): Message body
        preview_url (bool): Whether to show URL preview

    Returns:
        dict: JSON response from API
    Raises:
        requests.HTTPError: if request fails
    """
    url = "https://app.getgabs.com/sendservicemessages/sendmessages"

    payload = {
        "to": str(to_number),
        "text": {
            "body": message,
            "preview_url": preview_url
        },
        "type": "text",
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "api_key": settings.GETGABS_API_KEY
    }

    headers = {
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, timeout=15)
    response.raise_for_status()

    data = response.json()
    logger.info("WhatsApp message sent: %s", data)
    return data