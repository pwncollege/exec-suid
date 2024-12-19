FROM alpine:latest AS builder

RUN apk add --no-cache gcc musl-dev

COPY exec-suid.c .

ENV CC="gcc -static -O3 -s"
RUN $CC -o /usr/bin/exec-suid exec-suid.c

FROM alpine:latest

RUN apk add --no-cache bash python3 py3-pytest py3-yaml
RUN adduser -D user

COPY --from=builder /usr/bin/exec-suid /usr/bin/exec-suid
RUN chmod 6755 /usr/bin/exec-suid

COPY tests /tests

CMD ["pytest", "-v", "/tests"]
