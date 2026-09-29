FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data MODEL_DIR=/models/oron HF_HOME=/models/cache HOST=0.0.0.0 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/* && useradd -m -u 10001 studio
WORKDIR /studio
COPY app ./app
RUN mkdir /data /models && chown -R studio:studio /data /models
USER studio
EXPOSE 8080
CMD ["python", "-m", "app.server"]
