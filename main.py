"""
Main Application Server: Embeddable Widget & Lead-Capture Platform
Author: Deepak R
FlyRank Backend Capstone Project
"""

import os
import datetime
from typing import Optional, List, Dict
from fastapi import (
    FastAPI, Request, Response, HTTPException, status, Depends, Header, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    init_db, SessionLocal, Tenant, Widget, Submission,
    WidgetCreate, WidgetUpdate, WidgetResponse, WidgetPublicConfig,
    SubmissionCreate, SubmissionResponse, DashboardStats
)
from services import (
    ip_rate_limiter, widget_rate_limiter, validate_honeypot,
    geo_service, side_effect_service
)

# Initialize database tables
init_db()

app = FastAPI(
    title="Embeddable Widget & Lead-Capture Platform",
    version="1.0.0",
    description="Production-hardened backend for embeddable customer widgets, submission security, rate limiting, and geo-enrichment."
)

# -----------------------------------------------------------------------------
# Global CORS Configuration (Cross-Origin Support)
# Allows customer websites on different origins (e.g., localhost:5500, file://)
# to fetch configurations and submit form data without browser blocking.
# -----------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production: configurable per tenant
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["ETag", "Cache-Control", "X-RateLimit-Remaining"]
)

# Mount static directory for widget bundle delivery
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)


# -----------------------------------------------------------------------------
# Database Dependency & Tenant Authentication
# -----------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_tenant(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db)
) -> Tenant:
    """Enforces multi-tenant isolation. Rejects unauthenticated requests."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication header: 'X-API-Key'"
        )
    tenant = db.query(Tenant).filter(Tenant.api_key == x_api_key).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked API Key"
        )
    return tenant


# -----------------------------------------------------------------------------
# 1. Widget Delivery & Caching (Public Endpoints)
# -----------------------------------------------------------------------------
@app.get("/widget.js", summary="Serve Versioned Widget Bundle", tags=["Public Delivery"])
def serve_widget_script():
    """
    Serves the embeddable JavaScript snippet.
    Applies aggressive caching: max-age=1 year, immutable.
    """
    script_path = os.path.join(STATIC_DIR, "widget.js")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Widget script not found")
    
    response = FileResponse(script_path, media_type="application/javascript")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.get(
    "/widgets/{widget_id}/config",
    response_model=WidgetPublicConfig,
    summary="Public Widget Configuration",
    tags=["Public Delivery"]
)
def get_widget_public_config(
    widget_id: str,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Serves lightweight widget config for client-side rendering.
    Applies short-lived public caching (max-age=60 seconds).
    """
    widget = db.query(Widget).filter(Widget.id == widget_id, Widget.is_active == True).first()
    if not widget:
        raise HTTPException(status_code=404, detail=f"Widget '{widget_id}' not found or inactive")

    # Fast caching headers
    response.headers["Cache-Control"] = "public, max-age=60"
    return WidgetPublicConfig(
        id=widget.id,
        title=widget.title,
        widget_type=widget.widget_type,
        button_text=widget.button_text,
        is_active=widget.is_active
    )


# -----------------------------------------------------------------------------
# 2. Hardened Public Submission Endpoint
# -----------------------------------------------------------------------------
@app.post(
    "/widgets/{widget_id}/submissions",
    status_code=status.HTTP_201_CREATED,
    response_model=SubmissionResponse,
    summary="Public Form Submission",
    tags=["Submissions"]
)
async def create_submission(
    widget_id: str,
    payload: SubmissionCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Catches public internet form submissions:
    1. Payload Size Check: Rejects oversized payloads (>10KB) with 413.
    2. Rate Limiting: 429 on abuse burst.
    3. Honeypot Validation: Blocks bots filling hidden traps with 400.
    4. Resilient Geo-Enrichment: Provider A -> Provider B -> Fallback.
    5. Database Persistence: Stored with tenant isolation.
    6. Safe Side-Effects: Dispatches email; failure NEVER cancels the 201 response.
    """
    # 1. Boundary Guard: Reject oversized payload > 10KB
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10240:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload size exceeds 10KB limit"
        )

    # 2. Verify Widget Existence
    widget = db.query(Widget).filter(Widget.id == widget_id, Widget.is_active == True).first()
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found or inactive")

    # 3. Abuse Protection: Rate Limiting per IP & per Widget
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not ip_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please wait a few seconds before retrying."
        )
    if not widget_rate_limiter.is_allowed(widget_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Widget submission rate limit reached."
        )

    # 4. Spam Control: Honeypot trap inspection
    if not validate_honeypot(payload.hp_trap):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spam detection triggered (honeypot populated)"
        )

    # 5. Geolocation Fallback Chain (Graceful Degradation)
    city, country, provider_used = geo_service.enrich(client_ip)

    # 6. Persistent Storage
    submission = Submission(
        widget_id=widget.id,
        tenant_id=widget.tenant_id,
        email=payload.email,
        name=payload.name,
        custom_data=payload.custom_data,
        origin=request.headers.get("origin"),
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent"),
        geo_city=city,
        geo_country=country,
        geo_provider=provider_used
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    # 7. Safe Side Effect (Failure must NOT break or roll back submission)
    side_effect_service.trigger_submission_email(
        email=submission.email,
        widget_title=widget.title
    )

    return submission


# -----------------------------------------------------------------------------
# 3. Widget Management API (Multi-Tenant Authenticated CRUD)
# -----------------------------------------------------------------------------
@app.post(
    "/admin/widgets",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Widget",
    tags=["Widget Management"]
)
def create_widget(
    payload: WidgetCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    widget = Widget(
        tenant_id=tenant.id,
        title=payload.title,
        widget_type=payload.widget_type,
        button_text=payload.button_text,
        allowed_domains=payload.allowed_domains
    )
    db.add(widget)
    db.commit()
    db.refresh(widget)
    
    # Generate embed snippet
    embed_snippet = f'<script src="http://localhost:8000/widget.js?id={widget.id}"></script>'
    return WidgetResponse(
        id=widget.id,
        tenant_id=widget.tenant_id,
        title=widget.title,
        widget_type=widget.widget_type,
        button_text=widget.button_text,
        allowed_domains=widget.allowed_domains,
        is_active=widget.is_active,
        created_at=widget.created_at,
        embed_snippet=embed_snippet
    )


@app.get(
    "/admin/widgets",
    response_model=List[WidgetResponse],
    summary="List Tenant Widgets",
    tags=["Widget Management"]
)
def list_widgets(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Enforces tenant isolation: only returns widgets belonging to current tenant."""
    widgets = db.query(Widget).filter(Widget.tenant_id == tenant.id).all()
    results = []
    for w in widgets:
        results.append(WidgetResponse(
            id=w.id,
            tenant_id=w.tenant_id,
            title=w.title,
            widget_type=w.widget_type,
            button_text=w.button_text,
            allowed_domains=w.allowed_domains,
            is_active=w.is_active,
            created_at=w.created_at,
            embed_snippet=f'<script src="http://localhost:8000/widget.js?id={w.id}"></script>'
        ))
    return results


@app.put(
    "/admin/widgets/{widget_id}",
    response_model=WidgetResponse,
    summary="Update Widget",
    tags=["Widget Management"]
)
def update_widget(
    widget_id: str,
    payload: WidgetUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    widget = db.query(Widget).filter(
        Widget.id == widget_id,
        Widget.tenant_id == tenant.id
    ).first()
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found or unauthorized")

    if payload.title is not None:
        widget.title = payload.title
    if payload.button_text is not None:
        widget.button_text = payload.button_text
    if payload.allowed_domains is not None:
        widget.allowed_domains = payload.allowed_domains
    if payload.is_active is not None:
        widget.is_active = payload.is_active

    db.commit()
    db.refresh(widget)
    return WidgetResponse(
        id=widget.id,
        tenant_id=widget.tenant_id,
        title=widget.title,
        widget_type=widget.widget_type,
        button_text=widget.button_text,
        allowed_domains=widget.allowed_domains,
        is_active=widget.is_active,
        created_at=widget.created_at,
        embed_snippet=f'<script src="http://localhost:8000/widget.js?id={widget.id}"></script>'
    )


@app.delete(
    "/admin/widgets/{widget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Widget",
    tags=["Widget Management"]
)
def delete_widget(
    widget_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    widget = db.query(Widget).filter(
        Widget.id == widget_id,
        Widget.tenant_id == tenant.id
    ).first()
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found or unauthorized")

    db.delete(widget)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# 4. Owner Dashboard API (Analytics & Submissions)
# -----------------------------------------------------------------------------
@app.get(
    "/dashboard/submissions",
    response_model=List[SubmissionResponse],
    summary="List Tenant Submissions",
    tags=["Dashboard"]
)
def get_dashboard_submissions(
    widget_id: Optional[str] = Query(None),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Returns submissions belonging strictly to the authenticated tenant."""
    query = db.query(Submission).filter(Submission.tenant_id == tenant.id)
    if widget_id:
        query = query.filter(Submission.widget_id == widget_id)
    return query.order_by(Submission.created_at.desc()).all()


@app.get(
    "/dashboard/stats",
    response_model=DashboardStats,
    summary="Aggregated Tenant Analytics",
    tags=["Dashboard"]
)
def get_dashboard_stats(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Calculates real-time submission counts and country breakdowns."""
    total = db.query(Submission).filter(Submission.tenant_id == tenant.id).count()
    
    since_24h = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    last_24h = db.query(Submission).filter(
        Submission.tenant_id == tenant.id,
        Submission.created_at >= since_24h
    ).count()

    # Per-widget counts
    per_widget_raw = db.query(
        Submission.widget_id, func.count(Submission.id)
    ).filter(Submission.tenant_id == tenant.id).group_by(Submission.widget_id).all()
    per_widget = {wid: count for wid, count in per_widget_raw}

    # Top countries
    countries_raw = db.query(
        Submission.geo_country, func.count(Submission.id)
    ).filter(
        Submission.tenant_id == tenant.id,
        Submission.geo_country.isnot(None)
    ).group_by(Submission.geo_country).order_by(func.count(Submission.id).desc()).limit(5).all()
    top_countries = {country or "Unknown": count for country, count in countries_raw}

    return DashboardStats(
        total_submissions=total,
        submissions_last_24h=last_24h,
        top_countries=top_countries,
        per_widget_counts=per_widget
    )


# -----------------------------------------------------------------------------
# 5. Seed Demo Data Endpoint (One-Click Setup)
# -----------------------------------------------------------------------------
@app.post("/admin/seed", summary="Seed Demo Tenants and Widgets", tags=["Admin"])
def seed_demo_data(db: Session = Depends(get_db)):
    """Seeds Tenant A and Tenant B to prove multi-tenant isolation."""
    # Tenant A
    tenant_a = db.query(Tenant).filter(Tenant.api_key == "tenant-a-secret-key").first()
    if not tenant_a:
        tenant_a = Tenant(
            id="tenant-a-uuid-1111",
            name="Acme Marketing Inc",
            api_key="tenant-a-secret-key"
        )
        db.add(tenant_a)
        db.flush()

    # Tenant B
    tenant_b = db.query(Tenant).filter(Tenant.api_key == "tenant-b-secret-key").first()
    if not tenant_b:
        tenant_b = Tenant(
            id="tenant-b-uuid-2222",
            name="Beta Enterprise Corp",
            api_key="tenant-b-secret-key"
        )
        db.add(tenant_b)
        db.flush()

    # Widgets for Tenant A
    w_a = db.query(Widget).filter(Widget.id == "widget-demo-123").first()
    if not w_a:
        w_a = Widget(
            id="widget-demo-123",
            tenant_id=tenant_a.id,
            title="Join the VIP AI Engineering Newsletter",
            widget_type="signup_form",
            button_text="Get Weekly Insights"
        )
        db.add(w_a)

    # Widgets for Tenant B
    w_b = db.query(Widget).filter(Widget.id == "widget-beta-456").first()
    if not w_b:
        w_b = Widget(
            id="widget-beta-456",
            tenant_id=tenant_b.id,
            title="Beta Exclusive Software Waitlist",
            widget_type="signup_form",
            button_text="Join Beta Waitlist"
        )
        db.add(w_b)

    db.commit()
    return {
        "status": "seeded",
        "tenant_a_key": "tenant-a-secret-key",
        "tenant_a_widget_id": "widget-demo-123",
        "tenant_b_key": "tenant-b-secret-key",
        "tenant_b_widget_id": "widget-beta-456"
    }
