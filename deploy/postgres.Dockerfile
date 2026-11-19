FROM postgres:18.7-alpine3.24
RUN apk upgrade --no-cache \
    && apk add --no-cache su-exec \
    && ln -sf /sbin/su-exec /usr/local/bin/gosu
