#!/bin/bash
echo "Starting FastAPI on port 8001..."
uvicorn files.main:app --host 0.0.0.0 --port 8001 --workers 1 &

echo "Starting ngrok on port 8001..."
if [ -z "$NGROK_AUTHTOKEN" ]; then
    echo "Warning: NGROK_AUTHTOKEN is not set in your .env!"
else
    ngrok config add-authtoken $NGROK_AUTHTOKEN
fi
ngrok http 8001 --log=stdout
