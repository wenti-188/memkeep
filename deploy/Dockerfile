FROM python:3.11-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.huaweicloud.com/repository/pypi/simple \
    --trusted-host mirrors.huaweicloud.com \
    -r requirements.txt

COPY app ./app
COPY core ./core
COPY storage ./storage
COPY web ./web
COPY run.py .

EXPOSE 5051

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:5051/health || exit 1

CMD ["python", "run.py"]
