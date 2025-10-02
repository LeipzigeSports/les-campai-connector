ARG KC_VERSION=26.3.1

FROM quay.io/keycloak/keycloak:${KC_VERSION} AS builder

ENV KC_HEALTH_ENABLED=true
ENV KC_DB=postgres

WORKDIR /opt/keycloak

RUN [ "/opt/keycloak/bin/kc.sh", "build" ]

FROM quay.io/keycloak/keycloak:${KC_VERSION}

COPY --from=builder /opt/keycloak/ /opt/keycloak/

ENV KC_DB_USERNAME=admin
ENV KC_DB_PASSWORD=admin123
ENV KC_DB_URL_HOST=keycloak-db
ENV KC_DB_URL_DATABASE=keycloakdb

ENTRYPOINT [ "/opt/keycloak/bin/kc.sh" ]