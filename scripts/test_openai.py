import os
import requests
from dotenv import load_dotenv
import time

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("Error: OPENAI_API_KEY not found in .env file.")
    exit(1)

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

models_to_test = ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5-pro"]

print("Testing Latest OpenAI Models...\n")

for model in models_to_test:
    data = {
        "model": model,
        "messages": [{"role": "user", "content": f"Say 'Hello from {model}!'"}],
    }
    
    # gpt-5 and o1/o3 models use max_completion_tokens instead of max_tokens
    if "o1" not in model and "o3" not in model and "gpt-5" not in model:
        data["max_tokens"] = 20
    else:
        data["max_completion_tokens"] = 20

    print(f"Testing {model}...")
    start_time = time.time()
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data)
    elapsed = time.time() - start_time
    
    if response.status_code == 200:
        content = response.json()["choices"][0]["message"]["content"]
        print(f"  [Success in {elapsed:.2f}s] Response: {content.strip()}\n")
    else:
        print(f"  [Failed in {elapsed:.2f}s] Status code: {response.status_code}")
        print(f"  Response: {response.text}\n")
