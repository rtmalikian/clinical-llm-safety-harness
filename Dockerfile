FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/src \
    HARNESS_DB=/app/data/harness.db \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
COPY frontend ./frontend

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic

EXPOSE 8000
CMD ["uvicorn", "clinical_safety.api:app", "--host", "0.0.0.0", "--port", "8000"]
