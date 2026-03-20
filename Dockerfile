FROM python:3.11-slim

# Install ffmpeg at build time (not startup time)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Step 1: Install old setuptools that still has pkg_resources
# Step 2: Install whisper using that setuptools
# Step 3: Upgrade setuptools and install everything else
RUN pip install --no-cache-dir "setuptools<67" && \
    pip install --no-cache-dir --no-build-isolation openai-whisper==20231117 && \
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper tiny model at build time
RUN python -c "import whisper; whisper.load_model('tiny')"

# Copy app code
COPY . .

# Create folders the app expects
RUN mkdir -p static leads

ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]