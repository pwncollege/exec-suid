FROM alpine:latest AS builder

RUN apk add --no-cache gcc musl-dev

COPY exec.c .

ENV CC="gcc -static -O3 -s"
RUN $CC -o /usr/bin/exec exec.c

FROM alpine:latest

RUN apk add --no-cache python3 py3-pytest py3-yaml
RUN adduser -D user

COPY --from=builder /usr/bin/exec /usr/bin/exec
RUN chmod 6755 /usr/bin/exec

COPY tests /tests

CMD ["pytest", "-v", "/tests"]
