FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --quiet --no-cache-dir aiohttp websockets pyyaml
WORKDIR /app
CMD ["python", "server.py"]
