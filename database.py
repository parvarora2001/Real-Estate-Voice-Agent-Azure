from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, JSON, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# For now, use SQLite (easy). Later switch to PostgreSQL
DATABASE_URL = "sqlite:///./leads.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Contact Info (from form)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True)
    
    # Property Interest (from form)
    property_interest = Column(String, nullable=True)  # "3BR house downtown"
    budget = Column(Integer, nullable=True)
    
    # Lead Source
    source = Column(String, default="web_form")  # web_form, inbound_call, referral
    utm_source = Column(String, nullable=True)  # facebook, google, etc.
    
    # Call Status
    call_status = Column(String, default="pending")  # pending, calling, completed, no_answer, failed
    call_attempts = Column(Integer, default=0)
    last_call_at = Column(DateTime, nullable=True)
    next_callback_at = Column(DateTime, nullable=True)
    
    # Call Data
    twilio_call_sid = Column(String, nullable=True)
    call_duration = Column(Integer, nullable=True)
    conversation_transcript = Column(JSON, nullable=True)
    
    # Qualification Data (extracted from conversation)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Float, nullable=True)
    location_preference = Column(String, nullable=True)
    timeline = Column(String, nullable=True)
    financing_status = Column(String, nullable=True)
    
    # Lead Scoring
    lead_score = Column(String, default="cold")  # hot, warm, cold
    qualified = Column(Boolean, default=False)
    
    # Matched Properties
    matched_property_ids = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Appointment
    appointment_scheduled = Column(Boolean, default=False)
    appointment_datetime = Column(DateTime, nullable=True)

# Create tables
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()