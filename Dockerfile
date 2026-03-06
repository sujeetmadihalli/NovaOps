# Use an official Python runtime as a parent image
# We use Python 3.10 slim to keep the image size manageable while supporting heavy ML libraries
FROM python:3.10-slim

# Set environment variables to avoid python buffering and ensure smooth logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# We need build-essential for some ML libraries and curl for healthchecks
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
# We specifically install CPU-only PyTorch first to save gigabytes of space in the Docker image
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Ensure the local vector DB directory has proper permissions if it needs to be written to
RUN mkdir -p /app/chroma_db && chmod -R 777 /app/chroma_db

# Expose the FastAPI port
EXPOSE 8000

# Command to run the FastApi server using uvicorn
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
