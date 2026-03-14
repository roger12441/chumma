import requests

url = "http://localhost:8001/stt/synthesize"
data = {"text": "Hello, this is a test from Azure Text-To-Speech."}

print(f"Testing {url}...")
try:
    res = requests.post(url, json=data)
    if res.status_code == 200:
        print(f"Success! Received {len(res.content)} bytes of audio data.")
    else:
        print(f"Failed with status code: {res.status_code}")
        print(res.text)
except Exception as e:
    print(f"Error connecting: {e}")
