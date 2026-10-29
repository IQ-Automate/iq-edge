# IQ Edge — built on the home's own device by the Supervisor (no registry). Home Assistant's Python base image (Alpine + s6-overlay,
# hence init: false in config.yaml); BUILD_FROM is no longer passed by default, so it has a fixed default here.
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ENV IQ_EDGE_ARCH=${BUILD_ARCH} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The home's time zone database (the Bom dia speaks at the home's local time).
RUN apk add --no-cache tzdata

COPY app/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY app/iq_edge /app/iq_edge
WORKDIR /app

CMD ["python3", "-m", "iq_edge"]
