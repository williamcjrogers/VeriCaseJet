FROM rust:1.75-bookworm AS build
WORKDIR /src

COPY Cargo.toml Cargo.lock* ./
RUN mkdir -p src && echo "fn main() {}" > src/main.rs
RUN cargo build --release

COPY src ./src
RUN cargo build --release

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

