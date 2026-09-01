# SecurePay — Complete System Flow

This document describes the actual, current end-to-end flow of the SecurePay Django project: what apps exist, how a request moves through the system for merchant onboarding, payment, shipment tracking, label validation, and customer enquiries — and what is missing, broken, or unwired in each stage. All file references are relative to the repo root.

---

## 1. App map

| App | Path | Responsibility |
|---|---|---|
| `securepay` | `securepay/` | Project settings, root URLs, custom CORS middleware |
| `payments` | `payments/` | Merchant/order/customer models, merchant session auth, Razorpay + PhonePe payment integration, order listing |
| `merchant` | `merchant/` | Merchant signup/login endpoints and merchant-facing static pages (no models of its own — uses `payments.MerchantInfo`) |
| `tracking` | `tracking/` | Shipment model, AWB tracking (own + Shipsagar 3rd-party courier), shipping-label PDF forensic validator, customer post-delivery enquiry flow, HMAC link-signing, WhatsApp notifications |
| `adminpanel` | `adminpanel/` | Internal staff dashboard: admin auth, order/enquiry listing, stats, enquiry resolution |


---

## 2. End-to-end flow

### 2.1 Merchant onboarding & login

```
POST /merchants/create_merchant/  → CreateMerchant   (merchant/v1/create_merchant.py)
POST /merchants/login/            → LoginMerchant    (merchant/v1/create_merchant.py)
```

- `CreateMerchant` hashes the password with **unsalted SHA-512**, generates `merchant_key`/`merchant_salt` via `secrets.token_hex(4)` (8 hex chars), retries up to 10× on unique-constraint collisions, and returns `merchant_id`/`merchant_key`/`merchant_salt` in plaintext.
- `LoginMerchant` verifies the SHA-512 hash, mints a `session_token` (`secrets.token_urlsafe(32)`), and stores `merchant_<id>:<session_token> → merchant_id` in Redis with a **5-minute TTL** (`payments/auth.py:9`, refreshed on each authenticated request). Returned both in the JSON body and as a `token` cookie (`SameSite=Lax`, no `HttpOnly`/`Secure`).
- All later merchant-scoped endpoints validate via `payments/auth.py:get_merchant_id_from_token()`, which reads that Redis key.

### 2.2 Order & payment generation

Two independent payment integrations exist side by side in `payments/api/v1/`:

**Razorpay** (`generate_order.py`)
```
POST /payments/create_payment/  → CreatePayment
POST /payments/verify_payment/  → VerifyPayment
GET  /payments/v1/shipments/    → ShipmentListView
```
- `CreatePayment` validates the merchant session, converts the rupee amount to paise, and creates a Razorpay order via the SDK using keys hardcoded in `payments/config.py`. If the SDK/keys are unavailable it falls back to a **mock order** that is returned to the client but never persisted to `OrderInfo`. Integrate payment link flow, once merchant sends the create payment, we must send a payment link to merchant. That link will be used by customer to pay. 
- `VerifyPayment` looks up the order by `pa_order_id`, **marks it `order_status="paid"` and saves before checking the HMAC signature**, then performs the signature check afterward. An additional api for merchant in case they miss our payment update webhook. Merchant can call this api and get the status of payment.
- Follow api_doc_v1.md for order apis/webhooks.


**PhonePe** (`phonepe.py`) — the flow actually used by the merchant "store" checkout (Demo Store) (This flow wont be used in production):
```
POST /payments/phonepe/initiate/  → PhonePeInitiateView  (merchant-session-gated)
GET  /payments/phonepe/return/    → PhonePeReturnView    (public — browser redirect target)
POST /payments/phonepe/callback/  → PhonePeCallbackView  (public webhook, csrf_exempt)
```
- `PhonePeInitiateView` creates/updates `OrderInfo`, fetches an OAuth token (`phonepe_auth.py`), and initiates checkout against `settings.PHONEPE_INIT_URL`.
- `PhonePeReturnView` re-verifies status server-to-server and redirects the browser back to the merchant store with status/amount in the URL query string.
- `PhonePeCallbackView` updates `order_status` directly from the POST body.

### 2.3 Shipment creation & tracking

```
POST /tracking/create_shipment/                    → CreateShipment
POST /tracking/create_shipments_bulk/               → CreateBulkShipment   (CSV import)
GET  /tracking/track_shipment/<awb>/                → TrackShipmentShipsagar
GET  /tracking/track_shipment/shipsagar/<awb>/       → TrackShipmentShipsagar (duplicate route)
POST|GET /tracking/track_shipment/<awb>/delivered   → UpdateShipment
```
- `CreateShipment` creates a `Shipment`, links it to the matching `OrderInfo` by `pa_order_id`, and synchronously pushes to the third-party Shipsagar API.
- `CreateBulkShipment` does the same per-row from an uploaded CSV — including one blocking Shipsagar call per row.
- `TrackShipmentShipsagar` polls Shipsagar for status; when a shipment newly transitions to "delivered" it triggers `notify_customer_delivered()`.
- `UpdateShipment` is the local, manual "mark delivered" endpoint — `csrf_exempt`, accepts GET as well as POST, with an inline `# remove this in production` comment.
- To do-> ShipSagar webhook, any change in status of shipment id will be transfer to us via shipsagar webhook, make sure to recieve it correctly and update status of shipment. Also a button to track shipment manually using shipsagar tracking api.

### 2.4 Shipping-label PDF validation

```
POST /tracking/pdf/upload               → PDFValidator
POST /tracking/openapi/pdf/upload/      → PDFValidator (duplicate alias, CORS-public path)
```
`tracking/api/v1/validate.py` runs **two independent forensic pipelines** on the uploaded PDF:
1. `label_validator.validate_label()` — barcode/text cross-consistency, hidden/covered text, XMP lineage, revision history → `is_authentic`. To get awb number, order number and delivery partner. Fine tune this with more production examples to minimize errors.
2. `analyze_shipping_label_pdf()` (in the same file) — metadata suspicion, disclaimer-language ("sample only" etc.), AWB/barcode mismatch, font/glyph consistency, incremental-revision lineage → additive score → `verdict` (`likely_valid` / `needs_review` / `highly_suspicious`). Gives the risk score of a pdf, if its fraud or not. Fine tune to judge the pdf correctly and update DB. 
3. To Do -> Update DB with the details in these 2 cases. make sure uploaded pdf details are stored in DB for audit  purposes.

If the courier can't be identified from text/logo, a color-fingerprint fallback (`_detect_courier_from_color`) is tried — currently tuned only for Delhivery. The extracted AWB/order id is then used to link a `Shipment` to the matching `OrderInfo`. The response returns both engines' verdicts **without reconciling them** if they disagree.

### 2.5 Customer enquiry flow

1. On delivery, `notify_customer_delivered()` (`tracking/api/v1/track_shipments.py`) builds an HMAC-signed enquiry link (`tracking/signing.py`, keyed on Django's `SECRET_KEY`) and sends it via WhatsApp (GetGabs API).
2. Customer opens the link → frontend posts to:
   ```
   POST /tracking/enquiry/     → SubmitEnquiry   (auth = valid signature on the link)
   GET  /tracking/enquiries/   → EnquiryListView (merchant-session-gated)
   ```
   `SubmitEnquiry` verifies the signature, then creates an `EnquiryData` row.
3. Admin side (`adminpanel/`): staff review enquiries, add notes, and set a `resolution_status` (`unresolved` / `money_refunded` / `money_to_merchant`) — this is a status/audit field only; no actual refund or payout is triggered from here.
4. A management command, `generate_enquiry_link`, exists for manually printing a signed link for support use.
5. To Do -> Once enquiry  is  made, change in status must initiate payment flow, either refund to customer or money transfer to merchant.

### 2.6 Admin auth

`AdminLoginView` authenticates against Django's built-in `User` model (`is_staff`/`is_superuser` required), mints a Redis-backed session token (30-minute TTL), and all other admin endpoints go through `AdminAPIView.initial()` (`adminpanel/permissions.py`) which validates the bearer token and staff status on every request.

---

## 3. What's missing / broken


### Authentication gaps
- `CreateShipment`, `CreateBulkShipment`, `TrackShipmentShipsagar`, and `PDFValidator` have **no auth check at all** — any caller can create shipments against arbitrary orders, trigger third-party Shipsagar API calls, or upload PDFs for order linking. 
- The duplicate `POST /tracking/openapi/pdf/upload/` route sits under a CORS-public-allowed path prefix, so the (already-unauthenticated) label upload endpoint is reachable cross-origin from anywhere.
- `UpdateShipment` is `csrf_exempt` and mutable via GET.
- To Do -> Add API key validation in all the internal and open APIs.

### Secrets & config
- Hardcoded, committed secrets: Django `SECRET_KEY`, DB password, Razorpay keys (`payments/config.py`), PhonePe client secret (`securepay/settings.py` and `payments/config.py`), a Shipsagar bearer token (`tracking/api/v1/track_shipments.py`), and apparently-live `OPENAI_API_KEY`/`HUGGINGFACE_API_KEY` values that are **not referenced anywhere in the code** (dead but leaked).
- `GETGABS_API_KEY` is the literal placeholder `"your_production_api_key_here"` — WhatsApp delivery notifications are non-functional as configured (failures are caught and logged silently).
- `DEBUG = True` is hardcoded, not environment-gated.
- To do -> Before moving to production keep credentials somewhere safe , not on server.

### Operational / scale
- `push_to_shipsagar()` runs synchronously inside the request cycle for every shipment (including once per row in CSV bulk import) — no queue, retry, or circuit breaker. 
- `ShipmentListView`, `EnquiryListView`, and the admin list views all paginate **in Python** after loading the full filtered queryset — no `LIMIT`/`OFFSET` at the DB level.
- To Do -> Have proper retry mechanism, async flow wherever required.

---

## 4. Suggested priority order for fixes

1. Fix `VerifyPayment`'s save-before-verify ordering.
2. Add merchant-token auth to `CreateShipment`, `CreateBulkShipment`, `TrackShipmentShipsagar`, `PDFValidator`.
3. Rotate and move all hardcoded secrets to environment variables; remove the unused `OPENAI_API_KEY`/`HUGGINGFACE_API_KEY`.
4. Decide whether `GenerateOrder` should be wired up or deleted.
5. PDF validation scores, reject pdfs on basis of analysis and store each pdf info in DB.
6. Add automated tests, starting with the payment verification and enquiry flows.
7. Check complete merchant flow before moving to production.
8. Check the communication channel flow, make sure to get getgabs API key, save it and use wherever communication with customer is required.
9. Merchant Creation on our application might require KYC verification, GST verification. Add the required verification in flow create merchant flow.