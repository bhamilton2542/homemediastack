# Stage 1: compile alass-cli from source using an Alpine-based Rust image,
# so the resulting binary is linked against musl libc -- matching Bazarr's
# own Alpine base. A glibc-linked binary (from the standard Debian-based
# rust:slim image) will NOT run on Alpine, even with matching CPU architecture.
FROM rust:alpine AS alass-builder
RUN apk add --no-cache gcc musl-dev pkgconfig
RUN cargo install alass-cli --locked

# Stage 2: the actual Bazarr image, with the compiled alass binary copied in.
FROM lscr.io/linuxserver/bazarr:latest
COPY --from=alass-builder /usr/local/cargo/bin/alass-cli /usr/local/bin/alass-cli
RUN ln -sf /usr/local/bin/alass-cli /usr/local/bin/alass

# The post-processing script Bazarr will call after every subtitle download.
COPY sync_with_alass.sh /usr/local/bin/sync_with_alass.sh
RUN chmod +x /usr/local/bin/sync_with_alass.sh

# A one-time (or re-runnable) batch script to sync all already-downloaded
# subtitles, not just new ones going forward.
COPY bulk_sync_existing.sh /usr/local/bin/bulk_sync_existing.sh
RUN chmod +x /usr/local/bin/bulk_sync_existing.sh
