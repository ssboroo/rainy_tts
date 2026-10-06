FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data HOST=0.0.0.0 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/* && useradd -m -u 10001 studio
WORKDIR /studio
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir /data && chown -R studio:studio /data
# Bootstrap repairs volume ownership; app.railway drops to studio before starting
# the server and worker. Neither application runs as root.
USER root
EXPOSE 8080
CMD ["python", "-m", "app.railway"]
