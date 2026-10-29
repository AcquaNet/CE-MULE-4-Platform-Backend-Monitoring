# Fluent Bit (log ingestion) + a static busybox for the healthcheck: the official image is distroless
# (no shell, no wget). Fluent Bit's own registry: no Docker Hub pull limits.
FROM busybox:1.37.0-musl AS busybox
FROM cr.fluentbit.io/fluent/fluent-bit:5.1.4
COPY --from=busybox /bin/busybox /busybox
COPY fluent-bit.conf parsers.conf pipeline.lua /fluent-bit/etc/
