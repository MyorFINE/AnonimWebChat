FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TERMCHAT_DATA_DIR=/data
WORKDIR /srv/termchat
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run.py .
RUN useradd -r -u 1001 chat && mkdir /data && chown chat /data
USER chat
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8000/healthz')"
# Muhim: bitta worker (ulanishlar va limitlar xotirada saqlanadi)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
