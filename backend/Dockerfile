FROM golang:1.23-bookworm AS build
WORKDIR /app
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/backend ./cmd/server

FROM gcr.io/distroless/base-debian12
WORKDIR /app
COPY --from=build /bin/backend /bin/backend
EXPOSE 8080
ENTRYPOINT ["/bin/backend"]
