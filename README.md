# DHL eCommerce Integration for ERPNext

> **Automate DHL eCommerce (MNG Kargo) shipment creation, barcode label generation, and ZPL printing directly from ERPNext Delivery Notes — with a single click.**

[![ERPNext](https://img.shields.io/badge/ERPNext-v14%2B-blue)](https://erpnext.com)
[![Frappe Framework](https://img.shields.io/badge/Frappe-v14%2B-0089FF)](https://frappeframework.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)](https://python.org)

---

## What This App Does

This Frappe/ERPNext app connects your ERPNext instance to the **DHL eCommerce REST API** (powered by MNG Kargo infrastructure in Turkey) to:

- 🔐 **Authenticate** via JWT Bearer token (auto-refreshed every 8 hours)
- 📦 **Create shipment orders** from ERPNext Delivery Notes with one click
- 🖨️ **Print or download** shipping labels directly from the Delivery Note form
- 📋 **Log every API call** for traceability and debugging
- ⚙️ **Manage credentials** securely in an ERPNext Settings DocType

---

## Why Use This Integration?

| Problem | This App Solves It |
|---|---|
| Manual shipment entry in MNG portal | Auto-creates orders from ERPNext Delivery Note on submit |
| Copy-pasting tracking numbers | `referenceId` and barcode stored on the Delivery Note |
| Lost shipping labels | ZPL string saved to the document; reprint anytime |
| Expired JWT tokens | Automatic token refresh with expiry caching |
| No audit trail | Full request/response logging in DHL Cargo Log DocType |

---

## Supported API Endpoints

| Step | Endpoint | Description |
|---|---|---|
| 1 | `POST /mngapi/api/token` | Obtain Bearer JWT (valid 8 hours) |
| 2 | `POST /mngapi/api/standardcmdapi/createOrder` | Create shipment order |
| 3 | `POST /mngapi/api/barcodecmdapi/createbarcode` | Generate ZPL label |
| Optional | `POST /mngapi/api/pluscmdapi/createRecipient` | Pre-register recipient for branch detection |

Base URLs:
- **Test:** `https://testapi.mngkargo.com.tr`
- **Production:** `https://api.mngkargo.com.tr`

---

## Requirements

- **Frappe Framework** v14 or v15
- **ERPNext** v14 or v15
- **Python** 3.10+
- A valid **DHL eCommerce / MNG Kargo** customer account
- API credentials from [MNG Kargo ApiZone](https://apizone.mngkargo.com.tr) (production) or [Sandbox](https://sandbox.mngkargo.com.tr) (testing)

---

## Installation

```bash
# Navigate to your Frappe bench directory
cd /home/frappe/frappe-bench

# Get the app
bench get-app https://github.com/your-org/dhl_ecommerce_integration

# Install on your site
bench --site your-site.com install-app dhl_ecommerce_integration

# Run migrations
bench --site your-site.com migrate
```

---

## Configuration

### 1. Open DHL Cargo Settings

Go to **ERPNext → DHL Cargo Settings** and fill in:

| Field | Description |
|---|---|
| Customer Number | Your MNG Kargo customer number |
| Password | Your MNG Kargo API password |
| IBM Client ID | `x-ibm-client-id` from ApiZone portal |
| IBM Client Secret | `x-ibm-client-secret` from ApiZone portal |
| Use Test Environment | Enable for sandbox testing |

> ⚠️ Never hardcode credentials. All sensitive values are stored in the Settings DocType and never committed to version control.

### 2. Get Your API Credentials

**For Testing (Sandbox):**
1. Register at [https://sandbox.mngkargo.com.tr](https://sandbox.mngkargo.com.tr)
2. Create an application under **Applications → New Application**
3. Copy the `Client ID` and `Secret Key` shown once on screen
4. Subscribe to: Identity API, Standart Command API, Barcode Command API

**For Production:**
1. Register at [https://apizone.mngkargo.com.tr](https://apizone.mngkargo.com.tr)
2. Email `entegrasyon@mngkargo.com.tr` with your app name, static IP, and customer number
3. Await approval, then subscribe to the same three APIs

---

## Usage

### Creating a Shipment from a Delivery Note

1. Open a **Delivery Note** in ERPNext
2. Click **Create DHL Shipment** button (added by this app)
3. The app will:
   - Fetch or refresh the JWT token
   - Call `createOrder` with recipient and package data
   - Call `createBarcode` with the returned `referenceId`
   - Store the ZPL label string on the Delivery Note
4. Click **Print Label** to send to your Zebra printer

### Desi Calculation

Volumetric weight is calculated automatically:
desi = (width_cm × length_cm × height_cm) / 3000

text

### Key Field Rules

- `referenceId` — UPPERCASE, unique per order, max 20 characters
- `barcode` — must equal `referenceId`
- `cityCode` / `districtCode` — set to `0`; when `0`, `cityName` and `districtName` text fields are mandatory
- `customerId` / `refCustomerId` in recipient — always empty string `""`
- `printReferenceBarcodeOnError` — set to `1` to prevent operation halt on barcode errors

---

## Architecture
dhl_ecommerce_integration/
├── dhl_ecommerce_integration/
│ ├── doctype/
│ │ ├── dhl_cargo_settings/ # Credentials + JWT cache
│ │ └── dhl_cargo_log/ # API request/response audit log
│ ├── api/
│ │ ├── token.py # JWT fetch + refresh logic
│ │ ├── create_order.py # createOrder endpoint wrapper
│ │ └── create_barcode.py # createBarcode endpoint wrapper
│ └── hooks.py # Delivery Note on_submit trigger
├── README.md
└── setup.py

text

---

## ERPNext DocTypes Added

### DHL Cargo Settings
Stores all credentials and JWT cache. One record per site.

### DHL Cargo Log
Immutable audit log. Every API call records:
- Endpoint URL
- Request body (JSON)
- Response body (JSON)
- HTTP status code
- Timestamp
- Linked Delivery Note

---

## Example API Flow (Python/Frappe)

```python
import frappe, requests

def get_jwt_token():
    settings = frappe.get_single("DHL Cargo Settings")
    # Check cached token expiry
    if settings.jwt_token and not is_token_expired(settings.jwt_expire_date):
        return settings.jwt_token

    response = requests.post(
        f"{settings.base_url}/mngapi/api/token",
        headers={
            "x-ibm-client-id": settings.ibm_client_id,
            "x-ibm-client-secret": settings.get_password("ibm_client_secret"),
            "Content-Type": "application/json"
        },
        json={
            "customerNumber": settings.customer_number,
            "password": settings.get_password("password"),
            "identityType": 1
        }
    )
    data = response.json()
    # Cache token back to Settings
    frappe.db.set_value("DHL Cargo Settings", None, {
        "jwt_token": data["jwt"],
        "jwt_expire_date": data["jwtExpireDate"]
    })
    return data["jwt"]
```

---

## Troubleshooting

| Error | Likely Cause | Fix |
|---|---|---|
| `401 Unauthorized` | Expired or missing JWT | Token auto-refreshes; check `customerNumber`/`password` |
| `Branch not found` | Recipient district unknown | Use `createRecipient` first; contact MNG for manual branch mapping |
| `referenceId duplicate` | Same ID used twice | Ensure unique ID per Delivery Note (use DN name + timestamp) |
| ZPL label blank | `barcodes[].value` empty | Check `printReferenceBarcodeOnError` = `1`; review DHL Cargo Log |

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

[MIT](LICENSE)

---

## Keywords

`erpnext-shipping` · `dhl-ecommerce` · `mng-kargo` · `frappe-app` · `cargo-integration` · `zpl-label` · `shipment-automation` · `turkey-logistics` · `erpnext-plugin` · `barcode-generation`

---

## Related Projects

- [frappe/erpnext-shipping](https://github.com/frappe/erpnext-shipping) — Official ERPNext Shipping app (FedEx, Sendcloud, LetMeShip)
- [Frappe Framework Docs](https://frappeframework.com/docs)
- [ERPNext Docs](https://docs.erpnext.com)