#!/bin/bash
uvicorn main:app --host 0.0.0.0 --port 8000
apt-get update && apt-get install -y ffmpeg


### Step 2 — Add a `Procfile`
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT