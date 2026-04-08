# Python Dependency Auditor: pip-audit CVE scanning (ADR-051).
ARG BASE_IMAGE=localhost/apme-base:latest
FROM $BASE_IMAGE

ENV APME_DEP_AUDIT_VALIDATOR_LISTEN=0.0.0.0:50059
EXPOSE 50059

CMD ["apme-dep-audit-validator"]
