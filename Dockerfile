FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY photos.py .
COPY route_planner.py .
COPY templates templates
COPY static static
RUN base64 -d static/icon-192.png.b64 > static/icon-192.png \
 && base64 -d static/icon-512.png.b64 > static/icon-512.png \
 && base64 -d static/apple-touch-icon.png.b64 > static/apple-touch-icon.png
RUN mkdir -p /data
EXPOSE 1976
CMD ["gunicorn","--bind","0.0.0.0:1976","--workers","2","--threads","4","app:app"]
