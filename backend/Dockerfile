FROM golang:1.26-bookworm AS build
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/backend ./cmd/server
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/healthcheck ./cmd/healthcheck
RUN mkdir -p /storage/projects && chown -R 10001:10001 /storage

FROM gcr.io/distroless/base-debian12
WORKDIR /app
COPY --from=build /bin/backend /bin/backend
COPY --from=build /bin/healthcheck /bin/healthcheck
COPY --from=build --chown=10001:10001 /storage /storage
EXPOSE 8080
ENTRYPOINT ["/bin/backend"]
