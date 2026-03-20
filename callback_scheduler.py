from database import SessionLocal, Lead
from datetime import datetime, timedelta
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
BASE_URL = os.getenv("BASE_URL")

class CallbackScheduler:
    """Manages callback attempts for leads that didn't answer"""
    
    @staticmethod
    def schedule_callback(lead_id: int, attempt_number: int = 1):
        """Schedule next callback based on attempt number"""
        db = SessionLocal()
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        
        if not lead:
            db.close()
            return
        
        # Retry schedule: 30 min, 2 hours, 4 hours, next day
        retry_delays = {
            1: timedelta(minutes=30),
            2: timedelta(hours=2),
            3: timedelta(hours=4),
            4: timedelta(days=1)
        }
        
        # Max 4 attempts
        if attempt_number > 4:
            lead.call_status = "failed_max_attempts"
            db.commit()
            db.close()
            print(f"❌ Lead #{lead_id}: Max attempts reached")
            return
        
        # Calculate next callback time
        next_callback = datetime.now() + retry_delays.get(attempt_number, timedelta(hours=2))
        
        # Don't call between 9 PM and 9 AM
        if next_callback.hour >= 21 or next_callback.hour < 9:
            # Push to next day at 10 AM
            next_callback = next_callback.replace(hour=10, minute=0, second=0)
            if next_callback.hour >= 21:
                next_callback += timedelta(days=1)
        
        lead.next_callback_at = next_callback
        lead.call_status = "callback_scheduled"
        
        db.commit()
        db.close()
        
        print(f"📅 Lead #{lead_id}: Callback #{attempt_number} scheduled for {next_callback.strftime('%I:%M %p')}")
    
    @staticmethod
    async def process_callback_queue():
        """Process all pending callbacks"""
        db = SessionLocal()
        
        # Get leads ready for callback
        now = datetime.now()
        leads_to_call = db.query(Lead).filter(
            Lead.call_status == "callback_scheduled",
            Lead.next_callback_at <= now,
            Lead.call_attempts < 5
        ).all()
        
        print(f"\n⏰ Processing callback queue: {len(leads_to_call)} leads ready")
        
        for lead in leads_to_call:
            print(f"   Calling {lead.name} ({lead.phone}) - Attempt #{lead.call_attempts + 1}")
            
            # Trigger outbound call
            call_sid = await trigger_callback_call(lead)
            
            if call_sid:
                lead.twilio_call_sid = call_sid
                lead.call_status = "calling"
                lead.call_attempts += 1
                lead.last_call_at = datetime.now()
                db.commit()
                
                # Wait 3 seconds between calls to avoid rate limits
                await asyncio.sleep(3)
            else:
                # If call fails, schedule retry
                CallbackScheduler.schedule_callback(lead.id, lead.call_attempts + 1)
        
        db.close()
        print(f"✅ Callback queue processed\n")

async def trigger_callback_call(lead: Lead) -> str:
    """Trigger callback via Twilio API"""
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json"
        
        call_data = {
            "To": lead.phone,
            "From": TWILIO_PHONE_NUMBER,
            "Url": f"{BASE_URL}/voice/outbound?lead_id={lead.id}",
            "Method": "POST",
            "StatusCallback": f"{BASE_URL}/voice/status",
            "StatusCallbackEvent": ["completed", "no-answer", "busy", "failed"]
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=call_data,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            )
            
            if response.status_code == 201:
                result = response.json()
                return result['sid']
            else:
                print(f"❌ Twilio error: {response.text}")
                return None
                
    except Exception as e:
        print(f"❌ Callback trigger error: {e}")
        return None


async def run_callback_loop():
    """
    Background loop — started inside FastAPI lifespan.
    Checks for due callbacks every 60 seconds.
    """
    print("🔄 Callback runner started (polling every 60s)")
    while True:
        try:
            await CallbackScheduler.process_callback_queue()
        except Exception as e:
            print(f"❌ Callback loop error: {e}")
        await asyncio.sleep(60)

# Run callback processor
if __name__ == "__main__":
    import asyncio
    asyncio.run(CallbackScheduler.process_callback_queue())