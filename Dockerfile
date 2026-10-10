ARG BASE=python:3.12-slim
FROM ${BASE}
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install flask gunicorn
RUN useradd -u 10001 -m appuser
COPY app.py .
ARG VERSION=1.0
ARG BROKEN=0
ENV APP_VERSION=$VERSION APP_BROKEN=$BROKEN
USER 10001
EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--access-logfile", "-", "app:app"]
