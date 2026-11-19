FROM golang:1.26.11-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY main.go ./
RUN CGO_ENABLED=0 go build -trimpath -o /app/guestbook .

FROM alpine:3.23
WORKDIR /app
COPY --from=builder /app/guestbook /app/guestbook
COPY public/index.html /app/public/index.html
COPY public/script.js /app/public/script.js
COPY public/style.css /app/public/style.css
COPY public/jquery.min.js /app/public/jquery.min.js
USER 65532:65532
EXPOSE 3000
CMD ["./guestbook"]
