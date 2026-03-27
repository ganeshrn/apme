# CLI: calls Primary over gRPC for scan, runs fix/format locally.
# Mount project at /workspace; set APME_PRIMARY_ADDRESS to primary service.
FROM localhost/apme-base:latest

ENV APME_PRIMARY_ADDRESS=primary:50051
WORKDIR /workspace

ENTRYPOINT ["apme"]
CMD ["scan", "."]
