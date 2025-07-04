# Use Python 3.11 slim image
FROM python:3.11-slim

# Environment setup
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ curl git \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . .

# Clean previous build files
RUN rm -rf .venv _pycache_ *.egg-info build dist

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install crewai CLI
RUN pip install crewai[tools]

# Expose your app's port
EXPOSE 5002

# Health check (if applicable)
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://65.0.249.245:5002/health || exit 1

# Command to start the crew
CMD ["crewai", "run"]