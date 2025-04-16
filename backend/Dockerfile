# Use a specific Python version matching existing setup
FROM python:3.9-slim

WORKDIR /app

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (optional, uncomment if needed, e.g., for postgresql-client)
# RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
# Add asyncpg explicitly as it's needed for async SQLAlchemy with PostgreSQL
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir asyncpg

# Copy the entire backend application code
COPY . .

# --- Include Swagger/Redoc static files (from existing Verxe Dockerfile) ---
# Create static directory if it doesn't exist via code
RUN mkdir -p static
# Download Swagger UI files (use specific versions)
RUN wget -O static/swagger-ui-bundle.js https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.11.0/swagger-ui-bundle.js && \
    wget -O static/swagger-ui.css https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.11.0/swagger-ui.css
# Download Redoc files (use specific versions)
RUN wget -O static/redoc.standalone.js https://cdn.jsdelivr.net/npm/redoc@2.1.3/bundles/redoc.standalone.js
# Set permissions if necessary
RUN chmod -R 755 /app/static
# --- End Swagger/Redoc static files ---

# Expose the port the application runs on
EXPOSE 8000

# Command to run the application using Uvicorn
# Add --workers <num> for production deployments
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"] 