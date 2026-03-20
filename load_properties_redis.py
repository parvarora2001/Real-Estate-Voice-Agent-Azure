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

# Sample properties
properties = [
    {
        "id": "prop_001",
        "address": "123 Main Street",
        "city": "Downtown",
        "neighborhood": "Financial District",
        "property_type": "Condo",
        "bedrooms": 2,
        "bathrooms": 2,
        "price": 450000,
        "square_feet": 1200,
        "features": ["Hardwood floors", "Granite countertops", "In-unit laundry", "Balcony", "Parking"],
        "available": True
    },
    {
        "id": "prop_002",
        "address": "456 Oak Avenue",
        "city": "Westside",
        "property_type": "House",
        "bedrooms": 3,
        "bathrooms": 2.5,
        "price": 525000,
        "square_feet": 1800,
        "features": ["Large backyard", "Updated kitchen", "2-car garage"],
        "available": True
    },
    {
        "id": "prop_003",
        "address": "789 Beach Road",
        "city": "Waterfront",
        "property_type": "Condo",
        "bedrooms": 3,
        "bathrooms": 3,
        "price": 680000,
        "square_feet": 1600,
        "features": ["Ocean view", "Pool access", "Gym", "Concierge"],
        "available": True
    },
    {
        "id": "prop_004",
        "address": "321 Elm Street",
        "city": "Suburbs",
        "property_type": "House",
        "bedrooms": 4,
        "bathrooms": 3,
        "price": 595000,
        "square_feet": 2400,
        "features": ["Master suite", "Home office", "Finished basement", "3-car garage"],
        "available": True
    },
    {
        "id": "prop_005",
        "address": "555 Downtown Plaza",
        "city": "Downtown",
        "property_type": "Apartment",
        "bedrooms": 1,
        "bathrooms": 1,
        "price": 320000,
        "square_feet": 750,
        "features": ["High ceilings", "Exposed brick", "Rooftop access"],
        "available": True
    }
]

print("📦 Loading properties into Redis...\n")

for prop in properties:
    # Store each property by ID
    key = f"property:{prop['id']}"
    r.set(key, json.dumps(prop))
    
    # Also index by price range for fast lookup
    price_range = f"{prop['price'] // 100000}00k"
    r.sadd(f"properties:price:{price_range}", prop['id'])
    
    # Index by bedrooms
    r.sadd(f"properties:bedrooms:{prop['bedrooms']}", prop['id'])
    
    # Index by city
    r.sadd(f"properties:city:{prop['city'].lower()}", prop['id'])
    
    print(f"✅ Loaded: {prop['address']} - ${prop['price']:,}")

print(f"\n✨ Loaded {len(properties)} properties into Redis")
print(f"🔍 Test: redis-cli> GET property:prop_001")