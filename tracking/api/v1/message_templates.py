# WhatsApp message templates. Centralized here (rather than inlined as
# f-strings at each call site) so wording stays consistent and can be tuned
# in one place as more notification types are added.


def delivery_enquiry_message(order_id: str, enquiry_link: str, customer_name: str | None = None) -> str:
    """Sent when a shipment is marked delivered — see
    tracking.api.v1.track_shipments.notify_customer_delivered().

    Greets the customer by name when we have one, and always includes the
    signed enquiry link so they can report a problem in one tap.
    """
    greeting = f"Hi {customer_name.strip()}, " if customer_name and customer_name.strip() else "Hi, "
    return (
        f"{greeting}your order {order_id} has been marked as delivered.\n\n"
        f"If you didn't receive it, received the wrong item, or have any other "
        f"issue, please let us know here: {enquiry_link}"
    )
