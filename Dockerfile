# syntax=docker/dockerfile:1

FROM rust:latest AS builder
RUN apt-get update && apt-get install -y musl-tools && rm -rf /var/lib/apt/lists/*
RUN rustup target add x86_64-unknown-linux-musl
WORKDIR /usr/src/exec-suid
COPY src/ Cargo.toml ./
RUN cargo build --release --target x86_64-unknown-linux-musl

FROM python:latest
RUN pip install pytest pyyaml
RUN useradd -m hacker
COPY --from=builder --chmod=6755 /usr/src/exec-suid/target/x86_64-unknown-linux-musl/release/exec-suid /usr/bin/exec-suid
COPY tests /tests

CMD ["pytest", "-v", "/tests"]
