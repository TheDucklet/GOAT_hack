FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/backend
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd --create-home goat && mkdir -p /srv/backend/storage && chown -R goat:goat /srv/backend
USER goat
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
