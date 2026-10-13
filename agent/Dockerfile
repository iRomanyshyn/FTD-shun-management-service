FROM rust:1.98-slim-bookworm AS build

WORKDIR /src
COPY agent/Cargo.toml agent/Cargo.lock ./
COPY agent/src ./src
RUN cargo build --release --locked

FROM gcr.io/distroless/cc-debian12:nonroot

COPY --from=build /src/target/release/ftd-shun-agent /ftd-shun-agent
USER 10002:10001
ENTRYPOINT ["/ftd-shun-agent"]
