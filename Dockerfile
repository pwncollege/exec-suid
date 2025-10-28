# syntax=docker/dockerfile:1

FROM python:latest

RUN pip install pytest
RUN useradd -m hacker

COPY --from=result /bin/exec-suid /usr/bin/exec-suid
COPY tests /tests

RUN chmod 4755 /tests/programs/* && \
    chmod 6755 /usr/bin/exec-suid

CMD ["pytest", "-v", "/tests"]
