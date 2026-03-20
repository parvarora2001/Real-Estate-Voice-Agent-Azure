from database import SessionLocal, Lead
import json

db = SessionLocal()

print("\n" + "="*80)
print("📊 LEADS DATABASE")
print("="*80 + "\n")

leads = db.query(Lead).all()

if not leads:
    print("No leads found yet.\n")
else:
    for lead in leads:
        print(f"ID: {lead.id}")
        print(f"Name: {lead.name}")
        print(f"Phone: {lead.phone}")
        print(f"Email: {lead.email}")
        print(f"Interest: {lead.property_interest}")
        print(f"Budget: ${lead.budget:,}" if lead.budget else "Budget: Not specified")
        print(f"Source: {lead.source} ({lead.utm_source})")
        print(f"Call Status: {lead.call_status}")
        print(f"Call Attempts: {lead.call_attempts}")
        print(f"Twilio Call SID: {lead.twilio_call_sid}")
        print(f"Lead Score: {lead.lead_score}")
        print(f"Created: {lead.created_at}")
        
        if lead.conversation_transcript:
            print(f"\nConversation:")
            for msg in lead.conversation_transcript:
                role = "AI" if msg['role'] == 'assistant' else "User"
                print(f"  {role}: {msg['content']}")
        
        if lead.matched_property_ids:
            print(f"\nMatched Properties: {lead.matched_property_ids}")
        
        print("\n" + "-"*80 + "\n")

db.close()