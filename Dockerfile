# syntax=docker/dockerfile:1.7

FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d AS dependencies
WORKDIR /build

COPY recap_service/runtime-requirements.txt ./runtime-requirements.txt
RUN python -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --no-compile \
        --no-deps \
        --only-binary=:all: \
        --require-hashes \
        --prefix=/runtime-dependencies \
        --requirement runtime-requirements.txt

FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
ARG VCS_REF
RUN case "${VCS_REF}" in \
        ""|*[!0-9a-f]*) exit 1 ;; \
    esac \
    && test "${#VCS_REF}" -eq 40 \
    && groupadd --gid 10001 --system crabit \
    && useradd --uid 10001 --gid 10001 --system --no-create-home \
        --home-dir /app --shell /usr/sbin/nologin crabit

LABEL org.opencontainers.image.source="https://github.com/crabitteam2/crabit-data" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp

WORKDIR /app
COPY --from=dependencies /runtime-dependencies/ /usr/local/
COPY monthly_recap.py recap_presenter.py weekly_recap.py ./
COPY gunicorn.conf.py ./gunicorn.conf.py
COPY api/recap-generation-v1.yaml ./api/recap-generation-v1.yaml
COPY recap_service/ ./recap_service/

USER 10001:10001
EXPOSE 8081
ENTRYPOINT ["python", "-m", "gunicorn"]
CMD ["--config", "/app/gunicorn.conf.py", "recap_service.wsgi:application"]
