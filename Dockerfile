FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md REPORT.md ./
COPY src/ ./src/
COPY tests/ ./tests/
COPY data/ ./data/

# Default execution runs automated test verification followed by default --dry-run pipeline
CMD ["sh", "-c", "python3 -m unittest discover -s tests -v && python3 -m tx_order_lab.cli --dry-run --verify-raw"]
