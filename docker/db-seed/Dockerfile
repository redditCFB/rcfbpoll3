FROM postgres:18.4-alpine

RUN apk add --no-cache curl

COPY seed.sh /usr/local/bin/seed-local-fixture
ENTRYPOINT ["/usr/local/bin/seed-local-fixture"]
