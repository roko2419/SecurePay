# PDF Upload Open API

This API accepts a PDF file upload and authorizes the request using a merchant key passed in the `Authorization` header.

## Endpoint

`POST /tracking/openapi/pdf/upload/`

---

## Authentication

This endpoint requires a merchant authorization key.

### Supported header formats

#### Bearer format
```http
Authorization: Bearer <merchant_key>
```

#### Raw key format
```http
Authorization: <merchant_key>
```

If the authorization header is missing or invalid, the API returns `401 Unauthorized`.

---

## Request

### Content-Type

```http
multipart/form-data
```

### Form fields

| Field | Type | Required | Description |
|---|---|---:|---|
| `file` | file | Yes | PDF file to upload |

---

## Validation Rules

The API performs the following checks:

1. `Authorization` header must be present
2. Uploaded file must be provided
3. File name must end with `.pdf`
4. File content must not be empty

---

## Success Response

### Status
`200 OK`

### Response body
```json
{
  "ok": true,
  "message": "PDF accepted",
  "filename": "sample.pdf",
  "content_type": "application/pdf",
  "size_bytes": 245678,
  "pages": 12,
  "sha256": "6e8f0a8a3f6d9f7b3a4c8f0e1c2d3b4a5f6e7d8c9b0a1e2f3d4c5b6a7e8f9a0"
}
```

### Response fields

| Field | Type | Description |
|---|---|---|
| `ok` | boolean | Indicates request success |
| `message` | string | Success message |
| `filename` | string | Uploaded PDF filename |
| `content_type` | string | MIME type of uploaded file |
| `size_bytes` | integer | Size of uploaded file in bytes |
| `pages` | integer | Number of pages in the PDF |
| `sha256` | string | SHA-256 hash of the uploaded PDF bytes |

---

## Error Responses

### Missing authorization header
**Status:** `401 Unauthorized`

```json
{
  "ok": false,
  "error": "Authorization key is required"
}
```

### Invalid merchant key
**Status:** `401 Unauthorized`

```json
{
  "ok": false,
  "error": "Invalid merchant key"
}
```

### Non-PDF file uploaded
**Status:** `400 Bad Request`

```json
{
  "ok": false,
  "error": "only PDF file allowed"
}
```

### Empty file uploaded
**Status:** `400 Bad Request`

```json
{
  "ok": false,
  "error": "empty PDF file"
}
```

### Invalid PDF content
**Status:** `400 Bad Request`

```json
{
  "ok": false,
  "error": "invalid PDF: <details>"
}
```

---

## cURL Example

```bash
curl -X POST 'http://localhost:8000/tracking/openapi/pdf/upload/' \
  --header 'Authorization: Bearer YOUR_MERCHANT_KEY' \
  --form 'file=@"/path/to/sample.pdf"'
```

---

## Python Requests Example

```python
import requests

url = "http://localhost:8000/<your-pdf-upload-endpoint>/"
headers = {
    "Authorization": "Bearer YOUR_MERCHANT_KEY"
}

with open("sample.pdf", "rb") as f:
    files = {
        "file": ("sample.pdf", f, "application/pdf")
    }
    response = requests.post(url, headers=headers, files=files)

print(response.status_code)
print(response.json())
```

---