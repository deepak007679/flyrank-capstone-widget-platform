# FlyRank Capstone: Embeddable Widget & Lead-Capture Platform

> **"Let a customer define a widget, hand them one line of `<script>`, and safely catch everything the public internet throws back at you — validated, spam-filtered, enriched, and dashboarded."**

**Student:** Deepak R  
**Program:** FlyRank Backend Development Track Capstone  
**Language/Stack:** Python 3.10+ · FastAPI · SQLite/PostgreSQL · Pydantic · Vanilla JS  
**License:** MIT  

---

## 1. System Architecture Overview

The system enforces three strictly decoupled request paths:
1. **Authenticated Management Path:** Tenants configure widgets and view analytics.
2. **Public Delivery Path:** Browser caches static JS bundle and lightweight config.
3. **Public Submission Path:** Hardened gateway accepting cross-origin traffic from unknown origins with multi-layer abuse protection, geo-enrichment fallback, and resilient storage.

```
+------------------------------------------------------------------------------------+
|                                ACTOR 1: WIDGET OWNER                               |
|  [Admin Browser] ---> (X-API-Key) ---> POST /admin/widgets ---> [Tenant DB]        |
|                  ---> (X-API-Key) ---> GET /dashboard/stats                        |
+------------------------------------------------------------------------------------+

+------------------------------------------------------------------------------------+
|                                ACTOR 2: CUSTOMER SITE                              |
|  [Second-Origin Page: http://localhost:5500]                                       |
|    |                                                                               |
|    +---> <script src="http://localhost:8000/widget.js?id=123">                     |
|            |                                                                       |
|            +---> GET /widgets/123/config (Public · Cached · CORS)                  |
|            +---> Renders DOM Form with Hidden Honeypot Trap                        |
+------------------------------------------------------------------------------------+

+------------------------------------------------------------------------------------+
|                                ACTOR 3: WEBSITE VISITOR                            |
|  [Visitor Submits Form]                                                            |
|    |                                                                               |
|    v                                                                               |
|  POST /widgets/123/submissions (Cross-Origin CORS + Preflight OPTIONS)             |
|    |                                                                               |
|    +---> [Layer 1: Boundary Guard] (Payload size check >10KB -> 413)               |
|    +---> [Layer 2: Abuse Shield]   (Sliding Window Rate Limit -> 429)              |
|    +---> [Layer 3: Spam Defense]   (Honeypot Trap Inspection -> 400)               |
|    +---> [Layer 4: Geo-Enrichment] (Provider A -> Provider B -> Store without Geo) |
|    +---> [Layer 5: Persistence]    (SQLite/PostgreSQL with Tenant Isolation)       |
|    +---> [Layer 6: Side-Effects]   (Email Dispatched; Failure NEVER Blocks 201)    |
|    |                                                                               |
|    v                                                                               |
|  Returns HTTP 201 Created                                                          |
+------------------------------------------------------------------------------------+
```

---

## 2. Quick Start & Setup (One Documented Command)

### Prerequisites:
- Python 3.10 or higher installed
- Git

### One-Command Setup & Run:
```bash
# Clone the repository
git clone https://github.com/deepak007679/flyrank-capstone-widget-platform.git
cd flyrank-capstone-widget-platform

# Install dependencies and start server on port 8000
pip install fastapi uvicorn pydantic sqlalchemy pytest requests httpx
uvicorn main:app --reload --port 8000
```

### Seed Demo Data:
In a second terminal, seed the demonstration tenants and widgets:
```bash
curl -X POST http://localhost:8000/admin/seed
```
* **Tenant A API Key:** `tenant-a-secret-key` (Widget ID: `widget-demo-123`)
* **Tenant B API Key:** `tenant-b-secret-key` (Widget ID: `widget-beta-456`)

---

## 3. Running the Customer Site (Second-Origin Demonstration)

To demonstrate true cross-origin (CORS) delivery from a completely separate origin:

```bash
# Serve the customer test page on port 5500 (origin: http://localhost:5500)
cd customer_site
python -m http.server 5500
```
Open **`http://localhost:5500`** in your browser. You will see the widget automatically fetched from `http://localhost:8000`, rendered, and submitting form payloads across origins with active preflight handling.

---

## 4. Endpoints Reference Table

| Method | Endpoint | Auth | Purpose | Status Codes |
| :--- | :--- | :---: | :--- | :---: |
| `GET` | `/widget.js` | None | Immutable JavaScript embed bundle | `200` |
| `GET` | `/widgets/{id}/config` | None | Lightweight widget configuration | `200`, `404` |
| `POST` | `/widgets/{id}/submissions`| None | Public cross-origin submission | `201`, `400`, `413`, `429` |
| `POST` | `/admin/widgets` | `X-API-Key` | Create new widget for tenant | `201`, `401` |
| `GET` | `/admin/widgets` | `X-API-Key` | List tenant-isolated widgets | `200`, `401` |
| `PUT` | `/admin/widgets/{id}` | `X-API-Key` | Update widget options | `200`, `404` |
| `DELETE`| `/admin/widgets/{id}` | `X-API-Key` | Delete widget (RFC empty body) | `204`, `404` |
| `GET` | `/dashboard/submissions` | `X-API-Key` | Retrieve tenant leads | `200`, `401` |
| `GET` | `/dashboard/stats` | `X-API-Key` | Aggregated analytics & counts | `200`, `401` |
| `POST` | `/admin/seed` | None | Provision test tenants and widgets | `200` |

---

## 5. Running the Acceptance Probe Test Suite

All 6 acceptance probes from Section 13 are fully covered:
```bash
pytest -v tests/test_probes.py
```

### Probes Verified:
* **PROBE 1:** Cross-origin submission from `localhost:5500` stored and visible in dashboard.
* **PROBE 2:** Malformed email (422) and oversized payload >10KB (413) return clean 4xx, never 500.
* **PROBE 3:** Rate limiting burst returns 429; normal traffic resumes after window.
* **PROBE 4:** Provider A down $\rightarrow$ Provider B answers. Both down $\rightarrow$ stored anyway without geo data.
* **PROBE 5:** Simulated SMTP timeout throws $\rightarrow$ submission still returns 201 Created.
* **PROBE 6:** Filled honeypot trap field triggers 400 Bad Request.

---

## 6. Honest Limitations & Architectural Trade-offs

1. **In-Memory Rate Limiting:**
   - The sliding-window rate limiter currently uses a process-local Python dictionary. In a horizontally scaled cluster behind a load balancer, this should be replaced with Redis (`INCR` with `EXPIRE` or token bucket Lua scripts) so all instances share a unified state.
2. **Synchronous Geolocation Queries:**
   - The fallback chain runs synchronously before database insertion with a strict 1.5s timeout. Under extreme throughput, geo-enrichment should be offloaded to an asynchronous background worker (e.g., Celery or BullMQ) to reduce latency from ~80ms to $<15\text{ ms}$.
3. **Database Concurrency:**
   - SQLite is configured for local zero-dependency testing. Production deployments should point `DATABASE_URL` to a pooled PostgreSQL cluster with connection pooling (PgBouncer).
