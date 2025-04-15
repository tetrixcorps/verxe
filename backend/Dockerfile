FROM python:3.9-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc postgresql-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create static directory
RUN mkdir -p static

# Download Swagger UI files
RUN wget -O static/swagger-ui-bundle.js https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.15.5/swagger-ui-bundle.js
RUN wget -O static/swagger-ui.css https://cdn.jsdelivr.net/npm/swagger-ui-dist@4.15.5/swagger-ui.css
RUN wget -O static/redoc.standalone.js https://cdn.jsdelivr.net/npm/redoc@2.0.0-rc.65/bundles/redoc.standalone.js

# Set proper permissions
RUN chmod -R 755 /app

# Command to run when container starts
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"] 