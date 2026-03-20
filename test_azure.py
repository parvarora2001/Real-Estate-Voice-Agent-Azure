import os
from dotenv import load_dotenv
from openai import AzureOpenAI
import azure.cognitiveservices.speech as speechsdk
import redis

load_dotenv()

print("🧪 Testing Azure Connections...\n")

# Test 1: Azure OpenAI
print("1️⃣  Testing Azure OpenAI...")
try:
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION")
    )
    
    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[{"role": "user", "content": "Say 'Azure OpenAI is working!'"}],
        max_tokens=20
    )
    
    print(f"   ✅ {response.choices[0].message.content}\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")

# Test 2: Azure Speech
print("2️⃣  Testing Azure Speech...")
try:
    speech_config = speechsdk.SpeechConfig(
        subscription=os.getenv("AZURE_SPEECH_KEY"),
        region=os.getenv("AZURE_SPEECH_REGION")
    )
    print(f"   ✅ Speech Service Connected (Region: {speech_config.region})\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")

# Test 3: Redis
print("3️⃣  Testing Redis...")
try:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT")),
        password=os.getenv("REDIS_PASSWORD"),
        ssl=os.getenv("REDIS_SSL") == "True",
        decode_responses=True
    )
    
    r.ping()
    r.set("test_key", "Redis is working!")
    value = r.get("test_key")
    print(f"   ✅ {value}\n")
except Exception as e:
    print(f"   ❌ Error: {e}\n")

print("✨ All tests complete!")