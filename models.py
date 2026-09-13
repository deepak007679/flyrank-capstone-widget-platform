"""
Models, Schemas, and Database Layer
Embeddable Widget & Lead-Capture Platform
Author: Deepak R
"""

import os
import uuid
import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    create_engine, Column, String, Integer, Boolean, DateTime,
    ForeignKey, Text, JSON, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from pydantic import BaseModel, Field, EmailStr

# -----------------------------------------------------------------------------
# Database Configuration (PostgreSQL or SQLite fallback)
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./widgets_platform.db")

# SQLite needs check_same_thread=False for multithreading
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# -----------------------------------------------------------------------------
# SQLAlchemy Database Models (Tenant Isolated)
# -----------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    api_key = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    widgets = relationship("Widget", back_populates="tenant", cascade="all, delete-orphan")


class Widget(Base):
    __tablename__ = "widgets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    title = Column(String(120), nullable=False)
    widget_type = Column(String(50), default="signup_form")  # signup_form, cta, popover
    button_text = Column(String(50), default="Subscribe")
    allowed_domains = Column(String(255), default="*")  # Domain restriction for CORS / origin validation
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="widgets")
    submissions = relationship("Submission", back_populates="widget", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_widget_tenant_id", "tenant_id"),
    )


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    widget_id = Column(String(36), ForeignKey("widgets.id"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Form Payload
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(100), nullable=True)
    custom_data = Column(JSON, nullable=True)
    
    # Security & Abuse Metadata
    origin = Column(String(255), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(255), nullable=True)
    
    # Enriched Geolocation Data (Fallback Chain)
    geo_country = Column(String(100), nullable=True)
    geo_city = Column(String(100), nullable=True)
    geo_provider = Column(String(50), nullable=True)  # ProviderA, ProviderB, or None
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    widget = relationship("Widget", back_populates="submissions")

    __table_args__ = (
        Index("ix_submission_widget_created", "widget_id", "created_at"),
        Index("ix_submission_tenant_created", "tenant_id", "created_at"),
    )


def init_db():
    Base.metadata.create_all(bind=engine)


# -----------------------------------------------------------------------------
# Pydantic Schemas (Boundary Validation)
# -----------------------------------------------------------------------------
class WidgetCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    widget_type: str = Field("signup_form", pattern="^(signup_form|cta|popover)$")
    button_text: str = Field("Subscribe", min_length=1, max_length=50)
    allowed_domains: str = Field("*", max_length=255)


class WidgetUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    button_text: Optional[str] = Field(None, min_length=1, max_length=50)
    allowed_domains: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class WidgetResponse(BaseModel):
    id: str
    tenant_id: str
    title: str
    widget_type: str
    button_text: str
    allowed_domains: str
    is_active: bool
    created_at: datetime.datetime
    embed_snippet: str

    class Config:
        from_attributes = True


class WidgetPublicConfig(BaseModel):
    id: str
    title: str
    widget_type: str
    button_text: str
    is_active: bool


class SubmissionCreate(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Valid email address")
    name: Optional[str] = Field(None, max_length=100)
    custom_data: Optional[Dict[str, Any]] = None
    # Spam honeypot trap field (must be left empty by human users)
    hp_trap: Optional[str] = Field(None, alias="_hp_trap", max_length=200)

    class Config:
        populate_by_name = True
        extra = "ignore"


class SubmissionResponse(BaseModel):
    id: str
    widget_id: str
    email: str
    name: Optional[str]
    geo_country: Optional[str]
    geo_city: Optional[str]
    geo_provider: Optional[str]
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_submissions: int
    submissions_last_24h: int
    top_countries: Dict[str, int]
    per_widget_counts: Dict[str, int]
