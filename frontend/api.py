import requests
import os
from dotenv import load_dotenv

load_dotenv()  

API_KEY = os.getenv("API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL")

print("API KEY:", API_KEY)

def call_backend(question: str):
    response = requests.post(
        f"{API_BASE_URL}/api/query/",
        json={"question": question},
        headers={"x-api-key": API_KEY},
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(response.text)

    return response.json()