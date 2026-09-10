FROM python:3.12-slim

WORKDIR /app

# Copy both dependency files because requirements.txt includes requirements-core.txt.
COPY requirements-core.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Runtime application + migration assets.
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
