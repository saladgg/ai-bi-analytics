import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL")


def call_backend(question: str):
    if not API_KEY:
        raise RuntimeError("Set API_KEY (a client key from API_KEYS) for the demo UI.")
    response = requests.post(
        f"{API_BASE_URL}/api/query/",
        json={"question": question},
        headers={"x-api-key": API_KEY},
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(response.text)

    return response.json()
