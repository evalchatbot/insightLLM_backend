FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set environment variables (can be overridden at runtime)
ENV PYTHONUNBUFFERED=1
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""
ENV JWT_SECRET_KEY="supersecret"

EXPOSE 8000

# Use multiple workers for production
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
