# Primary daemon: gRPC server; runs engine + OPA + native + optional Ansible gRPC client.
# No cache mount; needs network to reach OPA and Ansible.
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

ENV APME_PRIMARY_LISTEN=0.0.0.0:50051
ENV APME_COLLECTION_CACHE=/sessions
EXPOSE 50051

CMD ["apme-primary"]
