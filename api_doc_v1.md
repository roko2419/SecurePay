# SecureUPI Merchant Order API (v1)

## Overview
After cart validation, the **Merchant Backend** creates an order in **SecureUPI**.  
SecureUPI returns a checkout token/URL that the frontend uses for payment redirection.  
Payment result is delivered to Merchant Backend via webhook.

---

## Base URL
```text
<<URL>>
```

## Authentication
Use merchant API token in Authorization header.

```http
Authorization: Bearer <merchant_api_token>
X-Merchant-Id: <merchant_id>
Content-Type: application/json
```
```http
merchant_api_token: sha512(merchant_key+order_id+merchant_salt)
```
---

## 1) Create Order

### Endpoint
```http
POST /v1/orders
```

### Request Body
```json
{
  "merchant_order_id": "ORD-2026-000123",
  "merchant_id": 46,
  "amount": 149900,
  "currency": "INR",
  "customer": {
    "name": "Sarthak Chavande",
    "email": "sarthak@example.com",
    "phone": "9869094746"
  },
  "shipping": {
    "name": "Sarthak Chavande",
    "line1": "Acme Avenue Ambedkar Road",
    "line2": "Kandivali West 1304",
    "city": "Mumbai",
    "state": "Maharashtra",
    "pincode": "400067",
    "country": "IN"
  },
  "return_url": "https://merchant.com/checkout/return",
  "cancel_url": "https://merchant.com/checkout/cancel",
  "webhook_url": "https://merchant.com/payments/webhook"
}
```

### Field Rules
- `merchant_order_id`: Order ID from merchant side
- `amount`: integer in **paise** (₹1499.00 => `149900`)
- `currency`: currently `INR`
- `customer`: Customer info from merchant side - name, email, phone
- `items`: at least one item (list of dictionaries)
- `items[].qty`: integer > 0
- `items[].unit_price`: integer in paise
- `return_url`:  where user is sent after payment flow completes (success/pending/failure).
- `cancel_url`: where user is sent if they cancel/close checkout before completing payment.
- `webhook_url`: optional override; if absent, dashboard webhook is used

### Success Response (201)
```json
{
  "order_id": "supi_ord_01K2XYZABC",
  "merchant_id": "46",
  "merchant_order_id": "ORD-2026-000123",
  "status": "CREATED",
  "amount": 149900,
  "currency": "INR",
  "payment_id": "supi_pay_01K2XYZDEF",
  "checkout_token": "chk_tkn_eyJhbGciOi...",
  "checkout_url": "https://checkout.secureupi.com/c/chk_tkn_eyJ...",
  "expires_at": "2026-08-13T15:10:00Z",
  "created_at": "2026-08-13T14:40:00Z"
}
```

### Error Responses
- `400` Invalid payload
- `401` Invalid/expired token
- `403` Merchant mismatch / unauthorized
- `409` Duplicate `merchant_order_id`
- `422` Business validation failure
- `429` Rate limit exceeded
- `500` Internal server error

#### Error Format
```json
{
  "error": {
    "code": "INVALID_AMOUNT",
    "message": "Amount must be >= 100",
    "field": "amount"
  }
}
```

---

## 2) Get Order Status

### Endpoint
```http
GET /v1/orders/{order_id}
```

### Headers
```http
Authorization: Bearer <merchant_api_token>
X-Merchant-Id: <merchant_id>
```
```http
merchant_api_token: sha512(merchant_key+order_id+merchant_salt)
```

### Response (200)
```json
{
  "order_id": "supi_ord_01K2XYZABC",
  "merchant_order_id": "ORD-2026-000123",
  "status": "SUCCESS",
  "amount": 149900,
  "currency": "INR",
  "payment_id": "supi_pay_01K2XYZDEF",
  "paid_at": "2026-08-13T14:45:11Z"
}
```

---

## 3) Webhook (SecureUPI -> Merchant)

SecureUPI sends payment updates to merchant webhook endpoint.

### Merchant Webhook Endpoint (example)
```http
POST https://merchant.com/payments/webhook
```

### Headers
```http
X-SecureUPI-Event: payment.success|payment.failed|payment.expired
X-SecureUPI-AuthToken: <authToken>
X-SecureUPI-Timestamp: <unix_timestamp>
Content-Type: application/json
```
```http
auth: sha512(merchant_key+raw_request_body+merchant_salt)
```

### Payload
```json
{
  "event": "payment.success",
  "event_id": "evt_01K2XYZZZZ",
  "created_at": "2026-08-13T14:45:12Z",
  "data": {
    "order_id": "supi_ord_01K2XYZABC",
    "merchant_order_id": "ORD-2026-000123",
    "payment_id": "supi_pay_01K2XYZDEF",
    "status": "SUCCESS",
    "amount": 149900,
    "currency": "INR",
    "utr": "631829102938",
    "method": "UPI"
  }
}
```

### Signature Verification
Compute expected signature over:

```text
<timestamp>.<raw_request_body>
```

Using `HMAC-SHA256` with webhook secret.

Pseudo logic:
```text
expected = HMAC_SHA256(webhook_secret, timestamp + "." + raw_body)
secure_compare(expected, X-SecureUPI-Signature)
```

### Webhook Retry Policy
- Any non-2xx response is retried
- Exponential backoff
- Merchant should return `200` quickly and process asynchronously

---

## 4) Order Status Lifecycle
- `CREATED` -> Order created, awaiting payment
- `PENDING` -> Payment flow initiated
- `SUCCESS` -> Payment successful (funds in escrow)
- `FAILED` -> Payment failed
- `EXPIRED` -> Checkout session timed out
- `REFUNDED` -> (optional/future)

--- 

## 5) cURL Example

### Create Order
```bash
curl --request POST "https://api.secureupi.com/v1/orders" \
  --header "Authorization: Bearer <merchant_api_token>" \
  --header "X-Merchant-Id: m_12345" \
  --header "Idempotency-Key: ORD-2026-000123-1" \
  --header "Content-Type: application/json" \
  --data '{
    "merchant_order_id": "ORD-2026-000123",
    "amount": 149900,
    "currency": "INR",
    "customer": {
      "name": "Sarthak Chavande",
      "email": "sarthak@example.com",
      "phone": "9869094746"
    },
    "items": [
      {
        "sku": "4434911842027",
        "name": "Charcoal Carg - S",
        "qty": 1,
        "unit_price": 149900
      }
    ],
    "return_url": "https://merchant.com/checkout/return",
    "cancel_url": "https://merchant.com/checkout/cancel"
  }'
```

### Get Order
```bash
curl --request GET "https://api.secureupi.com/v1/orders/supi_ord_01K2XYZABC" \
  --header "Authorization: Bearer <merchant_api_token>" \
  --header "X-Merchant-Id: m_12345"
```