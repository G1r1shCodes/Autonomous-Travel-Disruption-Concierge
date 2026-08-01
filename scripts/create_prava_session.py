import os
import requests
import webbrowser
from dotenv import load_dotenv

load_dotenv()

prava_key = os.getenv("PRAVA_API_KEY")
if not prava_key:
    print("PRAVA_API_KEY not found in .env")
    exit(1)

# Ensure we use the correct backend URL for sandbox
backend_url = "https://sandbox.api.prava.space/v1/sessions"

headers = {
    "Authorization": f"Bearer {prava_key}",
    "Content-Type": "application/json"
}

payload = {
    "user_id": "hackathon_test_user",
    "user_email": "test@example.com",
    "total_amount": "50.00",
    "currency": "USD",
    "description": "Hackathon Test Checkout",
    "purchase_context": [{
        "merchant_details": {
            "name": "Test Airline",
            "url": "https://example.com",
            "country_code_iso2": "US"
        },
        "product_details": [{
            "description": "Flight Rebooking",
            "unit_price": "50.00",
            "quantity": 1
        }],
        "effective_until_minutes": 15
    }]
}

print("Creating Prava session...")
response = requests.post(backend_url, headers=headers, json=payload)

if response.status_code in [200, 201]:
    data = response.json()
    iframe_url = data.get("iframe_url")
    print("\n[SUCCESS] Session created successfully!")
    print(f"Session ID: {data.get('session_id')}")
    print(f"Iframe URL: {iframe_url}")
    
    print("\nOpening the secure checkout page in your browser...")
    webbrowser.open(iframe_url)
    print("Please enter the test card details provided by your teammate in the browser window!")
else:
    print("\n[ERROR] Failed to create session.")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
