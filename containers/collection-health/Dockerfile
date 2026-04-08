# Collection Health validator: curated native rules on installed collections (ADR-051).
ARG BASE_IMAGE=localhost/apme-base:latest
FROM $BASE_IMAGE

ENV APME_COLLECTION_HEALTH_VALIDATOR_LISTEN=0.0.0.0:50058
EXPOSE 50058

CMD ["apme-collection-health-validator"]
