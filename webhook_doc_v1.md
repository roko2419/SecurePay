# SecureUPI Shipping Link API/Webhook (v1)

## Overview
After payment is successful and merchant creates a shipment with a courier partner,  
the merchant must attach courier shipping details (AWB / shipment ID) to the existing SecureUPI order.

This can be done in either way:

1. **API Push (recommended):** Merchant Backend -> SecureUPI  
2. **Webhook/Event (optional):** SecureUPI -> Merchant to confirm shipping link accepted/updated

---

## When to call this
Call only after:
- Order exists in SecureUPI (`order_id` or `merchant_order_id`)
- Payment state is payable/confirmed (`SUCCESS` or equivalent)
- Merchant has generated courier shipment details (AWB/shipment_id)

---

## 1) Link Shipment to Order (Merchant -> SecureUPI)

### Endpoint
```http
POST /v1/orders/{order_id}/shipping
```

> Alternative lookup endpoint (if you use merchant order number):
```http
POST /v1/orders/by-merchant-order-id/{merchant_order_id}/shipping
```

### Authentication
```http
Authorization: Bearer <merchant_api_token>
X-Merchant-Id: <merchant_id>
Content-Type: application/json
Idempotency-Key: <unique-key-for-this-shipping-link-call>
```

### Request Body
```json
{
  "shipment_id": "SHP_77891183565",
  "order_id": "supi_ord_01K2XYZABC",
  "merchant_order_id": "ORD-2026-000123",
  "awb": "77891183565",
  "courier": "bluedart",
  "service_type": "surface",
  "shipping_amount": 0,
  "currency": "INR",
}
```

### Field Rules
- `shipment_id`: merchant/courier shipment reference (required)
- `awb`: airway bill / tracking number (required)
- `courier`: normalized lowercase code (e.g. `bluedart`, `delhivery`, `xpressbees`)
- `shipping_amount`: integer in paise

---

## Success Response (201/200)
```json
{
  "ok": true,
  "order_id": "supi_ord_01K2XYZABC",
  "merchant_order_id": "ORD-2026-000123",
  "payment_id": "supi_pay_01K2XYZDEF",
  "shipping": {
    "shipment_id": "SHP_77891183565",
    "awb": "77891183565",
    "courier": "bluedart",
    "service_type": "surface",
    "status": "LINKED",
    "linked_at": "2026-08-13T16:50:12Z"
  }
}
```

---

## Error Responses
- `400` invalid request payload
- `401` invalid token
- `403` merchant not authorized for order
- `404` order not found
- `409` duplicate/conflicting shipment for same order
- `422` payment not successful yet / invalid shipping state
- `429` rate limited
- `500` internal error

### Error Format
```json
{
  "error": {
    "code": "ORDER_NOT_PAYABLE",
    "message": "Shipping cannot be linked before successful payment",
    "field": "order_id"
  }
}
```

---

## 2) Update Shipment Details (Merchant -> SecureUPI)

Use this when AWB/courier changes, re-ship happens, or tracking URL updates.

### Endpoint
```http
PATCH /v1/orders/{order_id}/shipping
```

### Request Body (example)
```json
{
  "shipment_id": "SHP_77891183565",
  "order_id": "supi_ord_01K2XYZABC",
  "merchant_order_id": "ORD-2026-000123",
  "awb": "77891183565",
  "courier": "bluedart",
  "service_type": "surface",
  "currency": "INR",
  "metadata": {
    "reason": "reassigned_after_pickup_failure"
  }
}
```

### Response
```json
{
  "ok": true,
  "order_id": "supi_ord_01K2XYZABC",
  "shipping": {
    "shipment_id": "SHP_77891183565",
    "awb": "77891183566",
    "courier": "bluedart",
    "status": "UPDATED",
    "updated_at": "2026-08-13T17:05:00Z"
  }
}
```

---

### Response: shipping.linked
```json
{
  "event": "shipping.linked",
  "event_id": "evt_01K2SHPLINK01",
  "created_at": "2026-08-13T16:50:12Z",
  "data": {
    "order_id": "supi_ord_01K2XYZABC",
    "merchant_order_id": "ORD-2026-000123",
    "payment_id": "supi_pay_01K2XYZDEF",
    "shipment_id": "SHP_77891183565",
    "awb": "77891183565",
    "courier": "bluedart",
    "tracking_url": "https://www.bluedart.com/tracking?awb=77891183565",
    "status": "LINKED"
  }
}
```

### Response: shipping.updated
```json
{
  "event": "shipping.updated",
  "event_id": "evt_01K2SHPUPD02",
  "created_at": "2026-08-13T17:05:00Z",
  "data": {
    "order_id": "supi_ord_01K2XYZABC",
    "shipment_id": "SHP_77891183565",
    "awb": "77891183566",
    "courier": "bluedart",
    "status": "UPDATED"
  }
}
```

### Response: shipping.link_failed
```json
{
  "event": "shipping.link_failed",
  "event_id": "evt_01K2SHPERR03",
  "created_at": "2026-08-13T16:49:40Z",
  "data": {
    "order_id": "supi_ord_01K2XYZABC",
    "merchant_order_id": "ORD-2026-000123",
    "reason_code": "ORDER_NOT_PAYABLE",
    "reason": "Shipping link attempted before successful payment"
  }
}
```

## 3) Shipping State Model
- `NOT_LINKED` -> No shipping attached
- `LINKED` -> Shipment attached to order
- `IN_TRANSIT` -> Optional courier sync state
- `DELIVERED` -> Optional courier sync state
- `RTO` -> Optional return-to-origin state
- `CANCELLED` -> Shipment cancelled
- `UPDATED` -> Shipping details changed

---

## 4) cURL Examples

### Link Shipping
```bash
curl --request POST "https://api.secureupi.com/v1/orders/supi_ord_01K2XYZABC/shipping" \
  --header "Authorization: Bearer <merchant_api_token>" \
  --header "X-Merchant-Id: m_12345" \
  --header "Idempotency-Key: ship-ORD-2026-000123-v1" \
  --header "Content-Type: application/json" \
  --data '{
    "shipment_id": "SHP_77891183565",
    "awb": "77891183565",
    "courier": "bluedart",
    "service_type": "surface",
    "tracking_url": "https://www.bluedart.com/tracking?awb=77891183565"
  }'
```

### Update Shipping
```bash
curl --request PATCH "https://api.secureupi.com/v1/orders/supi_ord_01K2XYZABC/shipping" \
  --header "Authorization: Bearer <merchant_api_token>" \
  --header "X-Merchant-Id: m_12345" \
  --header "Content-Type: application/json" \
  --data '{
    "awb": "77891183566",
    "tracking_url": "https://www.bluedart.com/tracking?awb=77891183566"
  }'
```
