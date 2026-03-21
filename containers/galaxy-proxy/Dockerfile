# Galaxy proxy: PEP 503 bridge from Ansible Galaxy to pip/uv.
# Serves collections as Python wheels on demand; caches internally.
# Mount cache volume at /cache for persistence across restarts.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[proxy]"

EXPOSE 8765

VOLUME /cache

ENTRYPOINT ["galaxy-proxy", "start"]
CMD ["--host", "0.0.0.0", "--port", "8765", "--cache-dir", "/cache"]
