# syntax=docker/dockerfile:1

FROM alpine:latest AS builder

RUN apk add --no-cache gcc musl-dev

COPY exec-suid.c .

ENV CC="gcc -static -O3 -s"
RUN $CC -o /usr/bin/exec-suid exec-suid.c

FROM python:latest

RUN pip install pytest pyyaml

RUN adduser -D user

COPY --from=builder --chown=0:0 --chmod=6755 /usr/bin/exec-suid /usr/bin/exec-suid

COPY tests /tests

CMD ["pytest", "-v", "/tests"]
