FROM postgres:18.4-alpine@sha256:9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15

RUN apk add --no-cache curl

COPY seed.sh /usr/local/bin/seed-local-fixture
ENTRYPOINT ["/usr/local/bin/seed-local-fixture"]
