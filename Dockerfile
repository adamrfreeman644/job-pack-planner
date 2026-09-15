FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY scheduler.py .
COPY templates templates
RUN mkdir -p /data
EXPOSE 1976
CMD ["gunicorn","--bind","0.0.0.0:1976","--workers","2","--threads","4","app:app"]
