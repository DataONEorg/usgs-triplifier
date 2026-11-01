# Apache Jena validates releases against the SHACL shapes. This stage
# downloads it, checks its SHA-512 checksum and builds validate-release.jar.
FROM eclipse-temurin:21-jdk AS jena
ARG JENA_VERSION=5.6.0
ADD https://archive.apache.org/dist/jena/binaries/apache-jena-${JENA_VERSION}.tar.gz \
    https://archive.apache.org/dist/jena/binaries/apache-jena-${JENA_VERSION}.tar.gz.sha512 \
    /tmp/
RUN cd /tmp && \
    echo "$(cut -d ' ' -f 1 apache-jena-${JENA_VERSION}.tar.gz.sha512)  apache-jena-${JENA_VERSION}.tar.gz" | sha512sum -c - && \
    tar xzf apache-jena-${JENA_VERSION}.tar.gz && \
    mv apache-jena-${JENA_VERSION} /opt/jena
COPY etl/jena/ /build/
RUN /build/build-validator.sh /opt/jena

FROM ontotext/graphdb:10.8.12
LABEL maintainer="DataONE <support@dataone.org>"

# GraphDB runs on the image's Java 11. Jena 5 needs Java 17 or later, so it
# gets a Java 21 runtime of its own, which is not on the PATH.
COPY --from=eclipse-temurin:21-jre /opt/java/openjdk /opt/java/jena-jre
COPY --from=jena /opt/jena /opt/jena
ENV JENA_HOME=/opt/jena \
    JENA_JAVA_HOME=/opt/java/jena-jre

# curl is for the readiness probe in the entrypoint
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Use uv to manage the python version
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /uvx /bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Copy and install the usgs-triplifier package
COPY usgs-triplifier/ ./usgs-triplifier/
RUN cd usgs-triplifier && uv sync --frozen --no-dev --no-editable
ENV PATH="/opt/venv/bin:$PATH"

# Copy ETL code and config
COPY etl/code/ ./code/
COPY etl/gnis-ld-config.ttl gnis-ld-config.ttl
COPY docker/entrypoint.sh entrypoint.sh
