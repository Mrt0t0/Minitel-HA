FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN pip install --quiet --no-cache-dir aiohttp websockets pyyaml
WORKDIR /app
CMD ["python", "server.py"]
