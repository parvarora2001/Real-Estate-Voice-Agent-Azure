"""
Azure Voice Agent - Production Ready
Real Estate Lead Qualification System
"""
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel, validator
from pydantic_settings import BaseSettings
from sqlalchemy.orm import Session
from openai import AzureOpenAI
import azure.cognitiveservices.speech as speechsdk
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from twilio.request_validator import RequestValidator
import redis
import httpx
import whisper
import asyncio
import os
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from database import Lead, SessionLocal

# ============================================================================
# CONFIGURATION
# ============================================================================

class Settings(BaseSettings):
    """Application configuration"""
    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str = "2024-08-01-preview"

    # Azure Speech
    azure_speech_key: str
    azure_speech_region: str

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_ssl: bool = False  # ✅ PATCH 1: Changed default True → False (local Redis fix)

    # Application
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:8000"
    max_call_duration: int = 300
    max_recording_length: int = 30
    conversation_cleanup_hours: int = 1

    class Config:
        env_file = ".env"

settings = Settings()

# ============================================================================
# GLOBAL STATE
# ============================================================================

openai_client: Optional[AzureOpenAI] = None
redis_client: Optional[redis.Redis] = None
whisper_model = None
twilio_validator: Optional[RequestValidator] = None
conversations: Dict[str, Dict] = {}

# ============================================================================
# VALIDATION MODELS
# ============================================================================

class LeadSubmission(BaseModel):
    """Lead form submission with validation"""
    name: str
    phone: str
    email: Optional[str] = None
    property_interest: Optional[str] = None
    budget: Optional[int] = None
    source: str = "web_form"
    utm_source: str = "direct"

    @validator('name')
    def validate_name(cls, v):
        v = v.strip()
        if len(v) < 2 or len(v) > 100:
            raise ValueError('Name must be 2-100 characters')
        if not re.match(r'^[a-zA-Z\s\-\'\.]+$', v):
            raise ValueError('Name contains invalid characters')
        return v

    @validator('phone')
    def validate_phone(cls, v):
        digits = re.sub(r'\D', '', v)
        if len(digits) < 10 or len(digits) > 15:
            raise ValueError('Invalid phone number')
        return '+' + digits if not v.startswith('+') else '+' + digits

    @validator('email')
    def validate_email(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email address')
        return v

    @validator('budget')
    def validate_budget(cls, v):
        if v and (v < 50000 or v > 50000000):
            raise ValueError('Budget out of reasonable range')
        return v

# ============================================================================
# APP INITIALIZATION
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    global openai_client, redis_client, whisper_model, twilio_validator

    print("\n🚀 Initializing Azure Voice Agent...\n")

    try:
        # Azure OpenAI
        openai_client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
            api_version=settings.azure_openai_api_version
        )
        print("✅ Azure OpenAI connected")

        # Redis
        redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            ssl=settings.redis_ssl,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True
        )
        redis_client.ping()
        print("✅ Redis connected")

        # Whisper (preload for faster first transcription)
        print("⏳ Loading Whisper model...")
        whisper_model = whisper.load_model("tiny")
        print("✅ Whisper model loaded")

        # Twilio validator
        twilio_validator = RequestValidator(settings.twilio_auth_token)
        print("✅ Twilio validator initialized")

        print("✅ Azure Speech configured")

        # ✅ PATCH 2: Start background callback loop inside lifespan
        from callback_scheduler import run_callback_loop
        asyncio.create_task(run_callback_loop())
        print("✅ Callback loop started")

        print("\n🎉 Ready to handle calls!\n")

    except Exception as e:
        print(f"❌ Initialization error: {e}")
        raise

    yield

    print("\n👋 Shutting down...")


app = FastAPI(
    lifespan=lifespan,
    title="Azure Voice Agent",
    description="AI-Powered Real Estate Lead Qualification System",
    version="2.0.0"
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        settings.frontend_url,
        settings.base_url
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def validate_twilio_signature(request: Request, form_data: dict) -> bool:
    """Validate request is from Twilio"""
    if not twilio_validator:
        return True
    signature = request.headers.get('X-Twilio-Signature', '')
    url = str(request.url)
    return twilio_validator.validate(url, form_data, signature)

def cleanup_old_conversations():
    """Remove conversations older than configured hours"""
    cutoff = datetime.now() - timedelta(hours=settings.conversation_cleanup_hours)
    to_remove = []

    for call_sid, conv in conversations.items():
        try:
            started = datetime.fromisoformat(conv.get("started_at", datetime.now().isoformat()))
            if started < cutoff:
                to_remove.append(call_sid)
        except:
            to_remove.append(call_sid)

    for call_sid in to_remove:
        del conversations[call_sid]

    if to_remove:
        print(f"🧹 Cleaned up {len(to_remove)} old conversations")

async def convert_audio_async(temp_mp3: str, temp_wav: str) -> bool:
    """Convert MP3 to WAV asynchronously"""
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-i', temp_mp3,
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            temp_wav,
            '-y',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception as e:
        print(f"❌ Audio conversion error: {e}")
        return False

def escape_xml(text: str) -> str:
    """Escape XML special characters"""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;"))

def format_budget(budget: int) -> str:
    """Format budget for natural speech"""
    if budget < 500000:
        return "under $500,000"
    elif budget < 750000:
        return "$500,000 to $750,000"
    elif budget < 1000000:
        return "$750,000 to $1 million"
    else:
        return "over $1 million"

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def serve_form():
    """Serve lead capture form"""
    try:
        with open("static/index.html") as f:
            return Response(content=f.read(), media_type="text/html")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Form not found")

@app.get("/api/status")
def status():
    """System status endpoint"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "services": {
            "openai": openai_client is not None,
            "redis": redis_client is not None,
            "whisper": whisper_model is not None
        },
        "active_calls": len(conversations)
    }

@app.get("/health")
def health():
    """Health check for load balancers"""
    try:
        if redis_client:
            redis_client.ping()
        return {"status": "healthy"}
    except:
        raise HTTPException(status_code=503, detail="Service unhealthy")

# ============================================================================
# LEAD SUBMISSION
# ============================================================================

@app.post("/api/submit-lead")
@limiter.limit("3/hour")
async def submit_lead(
    request: Request,
    lead_data: LeadSubmission,
    db: Session = Depends(get_db)
):
    """Handle form submission with duplicate detection"""
    try:
        print(f"\n📝 New lead: {lead_data.name} ({lead_data.phone})")

        # Check for recent duplicate
        recent_lead = db.query(Lead).filter(
            Lead.phone == lead_data.phone,
            Lead.created_at > datetime.now() - timedelta(hours=24),
            Lead.call_status.in_(["pending", "calling", "callback_scheduled"])
        ).first()

        if recent_lead:
            print(f"⚠️  Duplicate submission - using existing lead #{recent_lead.id}")
            return {
                "status": "duplicate",
                "message": "We'll call you soon! A call is already scheduled.",
                "lead_id": recent_lead.id
            }

        # Create new lead
        lead = Lead(
            name=lead_data.name,
            phone=lead_data.phone,
            email=lead_data.email,
            property_interest=lead_data.property_interest,
            budget=lead_data.budget,
            source=lead_data.source,
            utm_source=lead_data.utm_source,
            call_status="pending"
        )

        db.add(lead)
        db.commit()
        db.refresh(lead)

        print(f"✅ Lead saved (ID: {lead.id})")

        # Trigger outbound call
        call_sid = await trigger_outbound_call(lead)

        if call_sid:
            lead.twilio_call_sid = call_sid
            lead.call_status = "calling"
            lead.call_attempts += 1
            lead.last_call_at = datetime.now()
            db.commit()

            print(f"📞 Call initiated: {call_sid}")
            return {"status": "success", "lead_id": lead.id, "call_sid": call_sid}
        else:
            return {"status": "error", "message": "Failed to initiate call"}

    except Exception as e:
        print(f"❌ Submit error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

async def trigger_outbound_call(lead: Lead) -> Optional[str]:
    """Initiate outbound call via Twilio"""
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls.json"

        call_data = {
            "To": lead.phone,
            "From": settings.twilio_phone_number,
            "Url": f"{settings.base_url}/voice/outbound?lead_id={lead.id}",
            "Method": "POST",
            "StatusCallback": f"{settings.base_url}/voice/status",
            "StatusCallbackEvent": ["completed", "no-answer", "busy", "failed"],
            "MachineDetection": "DetectMessageEnd",
            "MachineDetectionTimeout": 5000
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=call_data,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token)
            )

            if response.status_code == 201:
                return response.json()['sid']
            else:
                print(f"❌ Twilio error: {response.text}")
                return None

    except Exception as e:
        print(f"❌ Outbound call error: {e}")
        return None

# ============================================================================
# VOICE ENDPOINTS
# ============================================================================

@app.post("/voice/incoming")
async def handle_incoming_call(request: Request):
    """Handle incoming calls"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")

    print(f"\n📞 Incoming call: {call_sid} from {from_number}")

    conversations[call_sid] = {
        "messages": [],
        "lead_data": {},
        "caller_number": from_number,
        "started_at": datetime.now().isoformat()
    }

    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">
        Hello! Thank you for calling about our properties.
        I'm your A I assistant. What type of property are you looking for?
    </Say>
    <Record maxLength="30" action="/voice/process" playBeep="true" transcribe="false"/>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@app.post("/voice/outbound")
async def handle_outbound_call(request: Request, lead_id: int):
    """Handle outbound calls with personalization"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    answered_by = form_data.get("AnsweredBy", "")

    # ✅ PATCH 3: AMD check — hang up immediately if voicemail/machine detected
    machine_statuses = (
        "machine_start",
        "machine_end_beep",
        "machine_end_silence",
        "machine_end_other",
        "fax"
    )
    if answered_by in machine_statuses:
        print(f"📵 Voicemail detected ({answered_by}) — hanging up: {call_sid}")
        with SessionLocal() as db:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                from callback_scheduler import CallbackScheduler
                CallbackScheduler.schedule_callback(lead.id, lead.call_attempts + 1)
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    with SessionLocal() as db:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()

        if not lead:
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Hello! Thank you for your interest.</Say>
    <Hangup/>
</Response>"""
            return Response(content=twiml, media_type="application/xml")

        greeting = f"Hi {lead.name}! Thanks for your interest in "
        greeting += f"finding a {lead.property_interest}. " if lead.property_interest else "our properties. "
        greeting += "I'm your A I assistant. "
        if lead.budget:
            greeting += f"I see you're looking in the {format_budget(lead.budget)} range. "
        greeting += "What location are you interested in?"

        print(f"\n📞 Outbound connected: {call_sid} → {lead.name}")

        conversations[call_sid] = {
            "messages": [],
            "lead_id": lead_id,
            "lead_data": {
                "name": lead.name,
                "phone": lead.phone,
                "property_interest": lead.property_interest,
                "budget": lead.budget,
            },
            "started_at": datetime.now().isoformat(),
        }

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{escape_xml(greeting)}</Say>
    <Record maxLength="30" action="/voice/process" playBeep="true" transcribe="false"/>
</Response>"""

        return Response(content=twiml, media_type="application/xml")


@app.post("/voice/process")
async def process_recording(request: Request):
    """Process caller responses"""
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid")
        recording_url = form_data.get("RecordingUrl")

        if not recording_url:
            return create_error_response("I didn't catch that. Could you repeat?")

        # Download audio
        audio_data = await download_recording(recording_url)
        if not audio_data:
            return create_error_response("I had trouble hearing that.")

        # Transcribe
        transcription = await transcribe_audio(audio_data)
        if not transcription:
            return create_error_response("I didn't quite catch that.")

        print(f"👤 User: \"{transcription}\"")

        # Update conversation
        conversation = conversations.get(call_sid, {"messages": [], "lead_data": {}})
        conversation["messages"].append({"role": "user", "content": transcription})

        # Check if ending
        if should_end_call(conversation["messages"]):
            return await end_call(call_sid, conversation)

        # Generate response
        ai_response = await generate_ai_response(conversation["messages"])
        print(f"🤖 AI: \"{ai_response}\"")

        conversation["messages"].append({"role": "assistant", "content": ai_response})
        conversations[call_sid] = conversation

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{escape_xml(ai_response)}</Say>
    <Record maxLength="30" action="/voice/process" playBeep="true" transcribe="false"/>
</Response>"""

        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        print(f"❌ Processing error: {e}")
        return create_error_response("I'm having technical difficulties.")


@app.post("/voice/status")
async def handle_call_status(request: Request):
    """Handle Twilio status callbacks"""
    try:
        form_data = await request.form()

        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        call_duration = form_data.get("CallDuration")
        answered_by = form_data.get("AnsweredBy")

        print(f"\n📱 Status: {call_sid} → {call_status}")
        if answered_by:
            print(f"   Answered by: {answered_by}")

        with SessionLocal() as db:
            lead = db.query(Lead).filter(Lead.twilio_call_sid == call_sid).first()

            if not lead:
                cleanup_old_conversations()
                return Response(content="OK", media_type="text/plain")

            had_conversation = call_sid in conversations and len(conversations[call_sid].get("messages", [])) > 0

            if call_status == "completed":
                is_real_answer = (
                    had_conversation or
                    (call_duration and int(call_duration) > 30) or
                    (answered_by == "human")
                )

                if is_real_answer:
                    lead.call_status = "completed"
                    lead.call_duration = int(call_duration) if call_duration else 0
                    print(f"   ✅ Real conversation")
                else:
                    lead.call_status = "no_answer"
                    print(f"   📵 Voicemail/No answer")
                    from callback_scheduler import CallbackScheduler
                    CallbackScheduler.schedule_callback(lead.id, lead.call_attempts)

            elif call_status in ["no-answer", "busy", "failed"]:
                lead.call_status = call_status.replace("-", "_")
                print(f"   📵 {call_status}")

                if lead.call_attempts < 4:
                    from callback_scheduler import CallbackScheduler
                    CallbackScheduler.schedule_callback(lead.id, lead.call_attempts)

            db.commit()

        cleanup_old_conversations()
        return Response(content="OK", media_type="text/plain")

    except Exception as e:
        print(f"❌ Status error: {e}")
        return Response(content="OK", media_type="text/plain")

# ============================================================================
# CORE AI FUNCTIONS
# ============================================================================

async def download_recording(recording_url: str) -> Optional[bytes]:
    """Download recording from Twilio"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                recording_url + ".mp3",
                auth=(settings.twilio_account_sid, settings.twilio_auth_token)
            )
            response.raise_for_status()
            return response.content
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None

async def transcribe_audio(audio_data: bytes) -> Optional[str]:
    """Transcribe with Azure Speech + Whisper fallback"""
    temp_mp3 = f"temp_{os.getpid()}.mp3"
    temp_wav = f"temp_{os.getpid()}.wav"

    try:
        with open(temp_mp3, "wb") as f:
            f.write(audio_data)

        if not await convert_audio_async(temp_mp3, temp_wav):
            return await transcribe_with_whisper(temp_mp3)

        speech_config = speechsdk.SpeechConfig(
            subscription=settings.azure_speech_key,
            region=settings.azure_speech_region
        )
        audio_config = speechsdk.AudioConfig(filename=temp_wav)
        recognizer = speechsdk.SpeechRecognizer(speech_config, audio_config)

        result = recognizer.recognize_once()

        for f in [temp_mp3, temp_wav]:
            if os.path.exists(f):
                os.remove(f)

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text.strip()
        else:
            with open(temp_mp3, "wb") as f:
                f.write(audio_data)
            return await transcribe_with_whisper(temp_mp3)

    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return await transcribe_with_whisper(temp_mp3)

async def transcribe_with_whisper(audio_file: str) -> Optional[str]:
    """Whisper fallback transcription"""
    try:
        result = whisper_model.transcribe(audio_file, fp16=False)
        if os.path.exists(audio_file):
            os.remove(audio_file)
        text = result["text"].strip()
        print(f"✅ Whisper: '{text}'")
        return text
    except Exception as e:
        print(f"❌ Whisper error: {e}")
        return None

async def generate_ai_response(messages: List[Dict]) -> str:
    """Generate GPT-4 response"""
    try:
        system_prompt = """You are a professional real estate assistant on a phone call.
Your goal: Qualify leads by gathering key information.
Ask about: property type, bedrooms, budget, location, timeline, financing.

Rules:
- Ask ONE question at a time
- Keep responses SHORT (1-2 sentences - you're on a phone)
- Be friendly and conversational
- Remember what they've said
- Don't repeat questions"""

        response = openai_client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            max_tokens=100,
            temperature=0.7
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ GPT-4 error: {e}")
        return "I understand. Can you tell me more?"

def should_end_call(messages: List[Dict]) -> bool:
    """Check if conversation should end"""
    user_msgs = [m for m in messages if m['role'] == 'user']

    if len(user_msgs) >= 5:
        return True

    if user_msgs:
        last = user_msgs[-1]['content'].lower()
        if any(w in last for w in ['goodbye', 'thanks', "that's all", "that's it"]):
            return True

    return False

async def end_call(call_sid: str, conversation: Dict) -> Response:
    """End call and save data"""
    print("\n✅ Ending call...")

    lead_data = await extract_lead_data(conversation["messages"])
    matching_props = find_properties_in_redis(lead_data)

    lead_id = conversation.get("lead_id")
    caller_number = conversation.get("caller_number")

    with SessionLocal() as db:
        if lead_id:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
        elif caller_number:
            lead = Lead(
                phone=caller_number,
                source="inbound_call",
                call_status="completed"
            )
            db.add(lead)
        else:
            lead = None

        if lead:
            lead.conversation_transcript = conversation["messages"]
            lead.bedrooms = lead_data.get("bedrooms")
            lead.budget = lead_data.get("budget") or lead.budget
            lead.location_preference = lead_data.get("location")
            lead.timeline = lead_data.get("timeline")
            lead.financing_status = lead_data.get("financing")
            lead.qualified = True
            lead.matched_property_ids = [p['id'] for p in matching_props] if matching_props else None

            if lead_data.get("financing") == "pre-approved" and "immediate" in str(lead_data.get("timeline", "")).lower():
                lead.lead_score = "hot"
            elif lead_data.get("budget") and lead_data.get("bedrooms"):
                lead.lead_score = "warm"
            else:
                lead.lead_score = "cold"

            db.commit()
            print(f"💾 Saved lead to database")

    save_lead_report(call_sid, conversation, lead_data, matching_props)

    if matching_props:
        msg = f"Great! I found {len(matching_props)} properties that match. An agent will call within 24 hours. Thank you!"
    else:
        msg = "Thank you! An agent will review your requirements and contact you within 24 hours."

    return Response(content=f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{escape_xml(msg)}</Say>
    <Hangup/>
</Response>""", media_type="application/xml")

async def extract_lead_data(messages: List[Dict]) -> Dict:
    """Extract structured data with GPT-4"""
    try:
        conv_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])

        prompt = f"""Extract lead info from this conversation.

{conv_text}

Return ONLY valid JSON:
{{"budget": number or null, "bedrooms": number or null, "location": string or null, "property_type": string or null, "timeline": string or null, "financing": string or null}}"""

        response = openai_client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0
        )

        result = response.choices[0].message.content
        if '```' in result:
            result = result.split('```')[1].replace('json', '').strip()

        return json.loads(result)
    except:
        return {}

def find_properties_in_redis(lead_data: Dict) -> List[Dict]:
    """Find matching properties"""
    try:
        if not lead_data.get('bedrooms'):
            return []

        prop_ids = redis_client.smembers(f"properties:bedrooms:{lead_data['bedrooms']}")
        matches = []

        for prop_id in prop_ids:
            prop_json = redis_client.get(f"property:{prop_id}")
            if prop_json:
                prop = json.loads(prop_json)
                if lead_data.get('budget') and prop['price'] > int(lead_data['budget']):
                    continue
                matches.append(prop)

        return matches[:3]
    except:
        return []

def save_lead_report(call_sid: str, conv: Dict, data: Dict, props: List[Dict]):
    """Save lead report to file"""
    try:
        os.makedirs("leads", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with open(f"leads/lead_{call_sid}_{timestamp}.json", "w") as f:
            json.dump({
                "call_sid": call_sid,
                "timestamp": timestamp,
                "lead_data": data,
                "matching_properties": props,
                "conversation": conv["messages"]
            }, f, indent=2)
    except:
        pass

def create_error_response(message: str) -> Response:
    """Create error TwiML response"""
    return Response(content=f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">{escape_xml(message)}</Say>
    <Record maxLength="30" action="/voice/process" playBeep="true"/>
</Response>""", media_type="application/xml")

# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)