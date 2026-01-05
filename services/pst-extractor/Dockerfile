# NOTE: Cargo.lock currently resolves AWS SDK crates that require rustc >= 1.88.
FROM rust:1.88-bookworm AS build
WORKDIR /src

COPY Cargo.toml Cargo.lock* ./
RUN mkdir -p src && echo "fn main() {}" > src/main.rs
RUN cargo build --release

COPY src ./src
# Cargo rebuilds based on file modification times. Because we generate a dummy
# src/main.rs during the dependency-caching step, the copied real sources can
# have older mtimes (from the host), causing Cargo to *skip rebuilding* and
# leaving us with a no-op binary. Touch sources after copy to force rebuild.
RUN find src -type f -exec touch {} + \
  && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    pst-utils \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /src/target/release/pst-extractor /usr/local/bin/pst-extractor

ENV WORK_DIR=/scratch
RUN mkdir -p /scratch

ENTRYPOINT ["pst-extractor"]

