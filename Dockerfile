FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY remote_app /app/remote_app
COPY scripts /app/scripts
COPY literature-library /app/literature-library
COPY remote-ui /app/remote-ui

CMD ["uvicorn", "remote_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
