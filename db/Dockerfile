# Migration-runner image (e6, E6-REQ-9). One-shot tool, not a network service:
# it connects to postgres, applies db/migrations/*.sql, and exits. Local host
# Python is 3.8 without psycopg2, so the runner needs a container — this is it,
# run via `make migrate` (compose `tools` profile, no published ports).
FROM python:3.12-slim
RUN pip install --no-cache-dir psycopg2-binary==2.9.10
WORKDIR /db
COPY migrate.py /db/migrate.py
COPY migrations /db/migrations
ENTRYPOINT ["python", "migrate.py"]
