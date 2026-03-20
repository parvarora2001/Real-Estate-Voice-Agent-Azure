import redis
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to Redis
r = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    password=os.getenv("REDIS_PASSWORD"),
    ssl=os.getenv("REDIS_SSL") == "True",
    decode_responses=True
)

print("🔍 Redis Database Contents\n")
print("="*60)

# Get all keys
all_keys = r.keys('*')
print(f"\n📊 Total keys: {len(all_keys)}\n")

# Group keys by type
property_keys = [k for k in all_keys if k.startswith('property:')]
index_keys = [k for k in all_keys if k.startswith('properties:')]
other_keys = [k for k in all_keys if not k.startswith('property')]

# Show properties
if property_keys:
    print("🏠 PROPERTIES")
    print("-"*60)
    for key in sorted(property_keys):
        prop_json = r.get(key)
        prop = json.loads(prop_json)
        print(f"\n{key}")
        print(f"  Address: {prop.get('address')}")
        print(f"  Type: {prop.get('property_type')}")
        print(f"  Bedrooms: {prop.get('bedrooms')}")
        print(f"  Price: ${prop.get('price'):,}")
        print(f"  Available: {prop.get('available')}")

# Show indexes
if index_keys:
    print("\n\n📑 INDEXES")
    print("-"*60)
    for key in sorted(index_keys):
        members = r.smembers(key)
        print(f"\n{key}: {members}")

# Show other keys
if other_keys:
    print("\n\n🔑 OTHER KEYS")
    print("-"*60)
    for key in sorted(other_keys):
        if not key.startswith('properties:'):
            value = r.get(key)
            print(f"{key}: {value}")

print("\n" + "="*60)
print("✨ Done!\n")