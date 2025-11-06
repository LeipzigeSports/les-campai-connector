FROM python:3.13-alpine3.21 AS builder

WORKDIR /tmp
COPY ./pyproject.toml ./poetry.lock ./

RUN set -ex && \
        python -m pip install --disable-pip-version-check --no-cache-dir poetry==2.1.4 && \
        poetry self add poetry-plugin-export==1.9.0 && \
        poetry export -n -f requirements.txt -o requirements.txt

FROM python:3.13-alpine3.21

WORKDIR /app

COPY --from=builder /tmp/requirements.txt ./
COPY ./les_campai_connector/ ./les_campai_connector/

RUN set -ex && \
        addgroup -S nonroot && \
        adduser -S nonroot -G nonroot && \
        chown -R nonroot:nonroot /app

RUN set -ex && \
        python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT [ "/usr/local/bin/python", "/app/les_campai_connector/cli.py" ]
CMD [ "sync" ]

USER nonroot
