# Use a lightweight official Python image
FROM python:3.11-slim

# Set Python build and runtime configurations
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PORT=8080

# Configure working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source tree and server assets
COPY src/ ./src
COPY scripts/ ./scripts

# Expose target application port
EXPOSE 8080

# Run serve_dashboard by default
CMD ["python", "scripts/serve_dashboard.py"]
