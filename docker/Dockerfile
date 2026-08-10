FROM ontotext/graphdb:10.8.12
LABEL maintainer="DataONE <support@dataone.org>"

# Install Python, pip, and system dependencies for geopandas/pyogrio
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        libgdal-dev \
        libgeos-dev \
        && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install the usgs-triplifier package
COPY usgs-triplifier/ ./usgs-triplifier/
RUN pip3 install --no-cache-dir --break-system-packages ./usgs-triplifier requests

# Copy ETL code and config
COPY etl/code/ ./code/
COPY etl/gnis-ld-config.ttl gnis-ld-config.ttl
COPY docker/entrypoint.sh entrypoint.sh
