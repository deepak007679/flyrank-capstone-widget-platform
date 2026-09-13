"""
Comprehensive Acceptance Probe Test Suite
Embeddable Widget & Lead-Capture Platform
Author: Deepak R

Tests verify all 6 acceptance probes specified in Capstone Section 13:
- PROBE 1: Cross-origin valid submission stored, 2xx, visible via dashboard.
- PROBE 2: Malformed and oversized payloads return clean 4xx, never 500.
- PROBE 3: Rate limiting burst returns 429; normal traffic succeeds after.
- PROBE 4: Geo fallback chain: Provider A down -> Provider B; both down -> stored anyway.
- PROBE 5: Failing email side-effect does NOT break submission (returns 201).
- PROBE 6: Honeypot trap filled by bot triggers 400 Bad Request.
- Additional: Multi-tenant isolation verified between Tenant A and Tenant B.
"""

import pytest
from fastapi.testclient import TestClient
from main import app
from services import ip_rate_limiter, widget_rate_limiter, geo_service, side_effect_service

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_teardown():
    # Reset limiters and mock states before each test run
    ip_rate_limiter.reset()
    widget_rate_limiter.reset()
    geo_service.simulate_provider_a_down = False
    geo_service.simulate_provider_b_down = False
    side_effect_service.simulate_failure = False
    # Seed default data
    client.post("/admin/seed")
    yield


# -----------------------------------------------------------------------------
# PROBE 1: POST a valid submission from second origin -> stored, 2xx, in dashboard
# -----------------------------------------------------------------------------
def test_probe_1_valid_cross_origin_submission():
    widget_id = "widget-demo-123"
    origin_header = "http://localhost:5500"  # Second origin simulation

    # 1. Test CORS preflight (OPTIONS)
    preflight = client.options(
        f"/widgets/{widget_id}/submissions",
        headers={
            "Origin": origin_header,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type"
        }
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "*"

    # 2. Submit valid form
    payload = {
        "name": "Sarah Connor",
        "email": "sarah@skynet-defense.org",
        "_hp_trap": ""
    }
    response = client.post(
        f"/widgets/{widget_id}/submissions",
        json=payload,
        headers={"Origin": origin_header}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "sarah@skynet-defense.org"
    submission_id = data["id"]

    # 3. Verify visible in dashboard for Tenant A
    dash_res = client.get(
        "/dashboard/submissions",
        headers={"X-API-Key": "tenant-a-secret-key"}
    )
    assert dash_res.status_code == 200
    subs = dash_res.json()
    assert any(s["id"] == submission_id for s in subs)


# -----------------------------------------------------------------------------
# PROBE 2: Malformed and oversized payload -> clean 4xx, never 500
# -----------------------------------------------------------------------------
def test_probe_2_malformed_and_oversized_payloads():
    widget_id = "widget-demo-123"

    # Malformed email (should return 422 or 400, never 500)
    bad_email_res = client.post(
        f"/widgets/{widget_id}/submissions",
        json={"email": "not-an-email-address", "name": "Test"}
    )
    assert bad_email_res.status_code in (400, 422)
    assert "500" not in str(bad_email_res.status_code)

    # Oversized payload (> 10KB)
    huge_string = "A" * 15000
    oversized_res = client.post(
        f"/widgets/{widget_id}/submissions",
        json={"email": "valid@email.com", "name": huge_string},
        headers={"Content-Length": "16000"}
    )
    assert oversized_res.status_code == 413
    assert "exceeds" in oversized_res.json()["detail"].lower()


# -----------------------------------------------------------------------------
# PROBE 3: Fire a burst of rapid submissions -> 429s appear, normal request passes
# -----------------------------------------------------------------------------
def test_probe_3_rate_limiting_burst():
    widget_id = "widget-demo-123"
    payload = {"email": "tester@example.com", "_hp_trap": ""}

    # Send 5 requests (within limit of 5 per 10s)
    for _ in range(5):
        res = client.post(f"/widgets/{widget_id}/submissions", json=payload)
        assert res.status_code == 201

    # 6th request from same IP within window must trigger 429
    burst_res = client.post(f"/widgets/{widget_id}/submissions", json=payload)
    assert burst_res.status_code == 429
    assert "rate limit exceeded" in burst_res.json()["detail"].lower()

    # Reset limiter simulating elapsed window -> normal request succeeds again
    ip_rate_limiter.reset()
    normal_res = client.post(f"/widgets/{widget_id}/submissions", json=payload)
    assert normal_res.status_code == 201


# -----------------------------------------------------------------------------
# PROBE 4: Geo fallback chain: Provider A down -> Provider B; both down -> stored
# -----------------------------------------------------------------------------
def test_probe_4_geo_fallback_chain():
    widget_id = "widget-demo-123"
    payload = {"email": "geo@test.com", "_hp_trap": ""}

    # Scenario 1: Normal (Provider A answers)
    res1 = client.post(f"/widgets/{widget_id}/submissions", json=payload)
    assert res1.status_code == 201
    assert res1.json()["geo_provider"] == "ProviderA"

    # Scenario 2: Provider A is down -> Provider B answers
    geo_service.simulate_provider_a_down = True
    res2 = client.post(f"/widgets/{widget_id}/submissions", json=payload)
    assert res2.status_code == 201
    assert res2.json()["geo_provider"] == "ProviderB"

    # Scenario 3: BOTH providers are down -> Degrade, never fail!
    geo_service.simulate_provider_b_down = True
    res3 = client.post(f"/widgets/{widget_id}/submissions", json=payload)
    assert res3.status_code == 201
    # Submission stored successfully without geo data
    assert res3.json()["geo_provider"] is None
    assert res3.json()["geo_country"] is None


# -----------------------------------------------------------------------------
# PROBE 5: Force email side-effect to throw -> submission still returns success
# -----------------------------------------------------------------------------
def test_probe_5_safe_side_effect_failure_does_not_block():
    widget_id = "widget-demo-123"
    side_effect_service.simulate_failure = True  # Force SMTP exception

    payload = {"email": "unbreakable@domain.com", "name": "Safe Buyer", "_hp_trap": ""}
    res = client.post(f"/widgets/{widget_id}/submissions", json=payload)

    # CRITICAL: Must return 201, never 500!
    assert res.status_code == 201
    assert res.json()["email"] == "unbreakable@domain.com"


# -----------------------------------------------------------------------------
# PROBE 6: Honeypot field filled like a bot -> blocked with 400
# -----------------------------------------------------------------------------
def test_probe_6_honeypot_spam_blocking():
    widget_id = "widget-demo-123"
    spam_payload = {
        "email": "bot@spammer.ru",
        "name": "Cheap Loans",
        "_hp_trap": "I am a scraper filling all fields!"  # Honeypot trap filled
    }
    res = client.post(f"/widgets/{widget_id}/submissions", json=spam_payload)
    assert res.status_code == 400
    assert "spam" in res.json()["detail"].lower()


# -----------------------------------------------------------------------------
# Multi-Tenant Isolation Test (Tenant A cannot see Tenant B data)
# -----------------------------------------------------------------------------
def test_multi_tenant_isolation():
    # Tenant A lists widgets
    res_a = client.get("/admin/widgets", headers={"X-API-Key": "tenant-a-secret-key"})
    assert res_a.status_code == 200
    widgets_a = [w["id"] for w in res_a.json()]
    assert "widget-demo-123" in widgets_a
    assert "widget-beta-456" not in widgets_a  # Tenant B's widget is HIDDEN

    # Tenant B lists widgets
    res_b = client.get("/admin/widgets", headers={"X-API-Key": "tenant-b-secret-key"})
    assert res_b.status_code == 200
    widgets_b = [w["id"] for w in res_b.json()]
    assert "widget-beta-456" in widgets_b
    assert "widget-demo-123" not in widgets_b  # Tenant A's widget is HIDDEN

    # Tenant B tries to delete Tenant A's widget -> 404/403
    hack_res = client.delete(
        "/admin/widgets/widget-demo-123",
        headers={"X-API-Key": "tenant-b-secret-key"}
    )
    assert hack_res.status_code in (404, 403)


# -----------------------------------------------------------------------------
# Cache-Control Headers Test
# -----------------------------------------------------------------------------
def test_cache_control_headers():
    # Widget.js bundle should be immutable long cache
    res_js = client.get("/widget.js")
    assert res_js.status_code == 200
    assert "max-age=31536000" in res_js.headers.get("Cache-Control", "")

    # Config endpoint should be short cache
    res_cfg = client.get("/widgets/widget-demo-123/config")
    assert res_cfg.status_code == 200
    assert "max-age=60" in res_cfg.headers.get("Cache-Control", "")
