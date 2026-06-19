# Frontend Service

The **Frontend** is the user-facing HTTP server for the Online Boutique microservices demo. It is written in Go and acts as the API gateway — rendering HTML pages for the browser and communicating with all other backend microservices via gRPC (and HTTP for the auth and shopping assistant services).

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Key Files Explained](#key-files-explained)
  - [main.go](#maingo)
  - [handlers.go](#handlersgo)
  - [middleware.go](#middlewarego)
  - [rpc.go](#rpcgo)
  - [deployment_details.go](#deployment_detailsgo)
  - [packaging_info.go](#packaging_infogo)
  - [money/money.go](#moneymoneogo)
  - [validator/validator.go](#validatorvalidatorg)
  - [genproto/](#genproto)
  - [templates/](#templates)
  - [static/](#static)
- [HTTP Routes](#http-routes)
- [Middleware Stack](#middleware-stack)
- [Backend Service Connections](#backend-service-connections)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [Dockerfile](#dockerfile)

---

## Overview

The frontend service:

- Serves an e-commerce storefront (product listing, product detail, cart, checkout, order confirmation).
- Handles user authentication (login / register) by delegating to an Auth Service over HTTP.
- Supports multi-currency display (INR, USD, EUR, CAD, JPY, GBP, TRY).
- Surfaces product recommendations and contextual advertisements.
- Optionally exposes a Shopping Assistant (AI chatbot) page.
- Integrates with OpenTelemetry for distributed tracing and Google Cloud Profiler for performance profiling.

---

## Architecture

```
Browser
   │
   ▼
Frontend (Go HTTP, :8080)
   │
   ├── gRPC ──► ProductCatalogService
   ├── gRPC ──► CurrencyService
   ├── gRPC ──► CartService
   ├── gRPC ──► RecommendationService
   ├── gRPC ──► CheckoutService
   ├── gRPC ──► ShippingService
   ├── gRPC ──► AdService
   ├── HTTP ──► AuthService          (/login, /register, /verify)
   ├── HTTP ──► ShoppingAssistantService
   └── HTTP ──► PackagingService     (optional)
```

---

## Project Structure

```
frontend/
├── main.go                  # Server bootstrap, routing, gRPC connections
├── handlers.go              # HTTP request handlers (pages & API endpoints)
├── middleware.go            # Logging, session-ID, and auth middlewares
├── rpc.go                   # Thin gRPC client wrappers
├── deployment_details.go    # Fetches GCP cluster/zone metadata at startup
├── packaging_info.go        # Optional packaging microservice HTTP client
├── go.mod / go.sum          # Go module definition and checksums
├── genproto/                # Protobuf-generated Go code (gRPC stubs)
│   ├── demo.pb.go
│   └── demo_grpc.pb.go
├── money/
│   ├── money.go             # Money arithmetic (sum, multiply, validation)
│   └── money_test.go
├── validator/
│   ├── validator.go         # Input validation for form payloads
│   └── validator_test.go
├── templates/               # Go HTML templates
│   ├── home.html
│   ├── product.html
│   ├── cart.html
│   ├── order.html
│   ├── error.html
│   ├── ad.html
│   ├── assistant.html
│   └── recommendations.html
└── static/                  # Static assets served under /static/
    ├── styles/              # CSS files (cart, order, bot)
    ├── icons/               # SVG icons and logos
    └── images/              # Banner and product images
```

---

## Key Files Explained

### `main.go`

The entry point of the service. It is responsible for:

1. **Logging** — initialises a structured JSON logger (`logrus`) that outputs to stdout with RFC3339Nano timestamps.
2. **OpenTelemetry tracing** — when `ENABLE_TRACING=1`, creates an OTLP/gRPC trace exporter and registers a `TracerProvider` that samples every request.
3. **Google Cloud Profiler** — when `ENABLE_PROFILER=1`, starts the Stackdriver profiler in a goroutine (retries up to 3 times).
4. **gRPC connections** — reads service addresses from environment variables and dials each backend service using `grpc.NewClient` with OTel stats handler for automatic span propagation.
5. **Router** — registers all HTTP routes with `gorilla/mux` and wraps the router with the middleware chain.
6. **Server** — calls `http.ListenAndServe` on `LISTEN_ADDR:PORT` (default `:8080`).

Key constants defined here:
- `port = "8080"` — default listen port.
- `defaultCurrency = "INR"` — currency shown when no cookie is set.
- `cookieMaxAge = 172800` — 48-hour cookie lifetime.
- `whitelistedCurrencies` — the set of currencies the UI accepts.

The `frontendServer` struct holds all gRPC `*grpc.ClientConn` references plus the addresses of the Auth and Shopping Assistant services (which are HTTP, not gRPC).

---

### `handlers.go`

Contains one handler function per HTTP route. Notable handlers:

| Handler | Description |
|---|---|
| `homeHandler` | Fetches all products and converts prices to the user's currency, then renders the home template. Auto-detects GCP by probing `metadata.google.internal`. |
| `productHandler` | Fetches a single product, its price, recommendations, and optional packaging info, then renders the product page. |
| `addToCartHandler` | Validates the POST form, then calls the Cart gRPC service to add the item. |
| `viewCartHandler` | Fetches cart items, converts each price, calculates shipping quote and total, then renders the cart page. |
| `placeOrderHandler` | Validates the checkout form (address + credit card), calls the Checkout gRPC service, and renders the order confirmation. |
| `setCurrencyHandler` | Validates the submitted currency code and persists it in a cookie. |
| `loginHandler` | On GET renders the login form. On POST forwards credentials to the Auth service; on success stores `shop_auth` and `shop_username` cookies. |
| `registerHandler` | Same flow as login but calls the registration endpoint. |
| `assistantHandler` | Renders the shopping assistant (chatbot) page. |
| `chatBotHandler` | Proxies a POST body to the Shopping Assistant service and returns its response as JSON. |
| `getProductByID` | REST endpoint that returns a single product as JSON (used by the chatbot UI). |
| `logoutHandler` | Expires all cookies and redirects to `/login`. |

Helper functions:
- `renderMoney` — formats a `pb.Money` value as a currency symbol + decimal string (e.g. `₹1299.00`).
- `renderCurrencyLogo` — maps currency code to its symbol.
- `chooseAd` — randomly picks one ad from the Ad service's response.
- `injectCommonTemplateData` — merges page-specific data with common template variables (session ID, currency, platform name, username, etc.).

---

### `middleware.go`

Three middleware layers applied to every request:

1. **`logHandler`** — wraps the `ResponseWriter` to capture status code and byte count, attaches a unique request ID (UUID), and logs request start/complete with timing.

2. **`ensureSessionID`** — checks for a `shop_session-id` cookie. If absent, generates a new UUID (or uses a fixed ID when `ENABLE_SINGLE_SHARED_SESSION=true`) and sets the cookie. The session ID is stored in the request context so handlers can read it via `sessionID(r)`.

3. **`requireAuth`** — for every route **except** `/login`, `/register`, `/_healthz`, `/robots.txt`, and `/static/*`, checks for a `shop_auth` cookie and validates it against the Auth service's `/verify` endpoint. On failure, clears the stale cookie and redirects to `/login`.

---

### `rpc.go`

Thin wrapper functions over the auto-generated gRPC stubs. Each function creates a new client from an existing `*grpc.ClientConn` and performs a single RPC call:

| Function | Backend service | Description |
|---|---|---|
| `getCurrencies` | CurrencyService | Returns whitelisted currency codes. |
| `getProducts` | ProductCatalogService | Lists all products. |
| `getProduct` | ProductCatalogService | Fetches a single product by ID. |
| `getCart` | CartService | Returns cart items for a user. |
| `emptyCart` | CartService | Clears the user's cart. |
| `insertCart` | CartService | Adds an item to the cart. |
| `convertCurrency` | CurrencyService | Converts a `Money` value to a target currency. |
| `getShippingQuote` | ShippingService | Gets a shipping cost estimate, then converts it to the user's currency. |
| `getRecommendations` | RecommendationService | Returns up to 4 recommended products (fetches full product details for each ID). |
| `getAd` | AdService | Fetches contextual ads with a 100 ms timeout. |

---

### `deployment_details.go`

Runs an `init()` function at startup that asynchronously fetches GCP-specific metadata (pod hostname, GKE cluster name, zone) via the GCP Compute Metadata API. The results are stored in `deploymentDetailsMap` and injected into every HTML template so the UI can display where the pod is running — useful for demonstrating multi-cluster or canary deployments.

---

### `packaging_info.go`

Optional integration with a "Packaging" microservice (a separate Google Cloud demo component). If the `PACKAGING_SERVICE_URL` environment variable is set, the product page will fetch weight and dimensions (width, height, depth) for the product and pass them to the template. The fetch is done over plain HTTP GET.

---

### `money/money.go`

A pure-Go library for arithmetic on `pb.Money` (a Protobuf type with `units`, `nanos`, and `currency_code` fields). Provides:

- `IsValid` / `IsZero` / `IsPositive` / `IsNegative` — predicates.
- `AreSameCurrency` / `AreEquals` — comparison helpers.
- `Negate` — sign flip.
- `Sum` — adds two same-currency `Money` values with correct nanos carry logic.
- `MultiplySlow` — multiplies a `Money` value by a uint via repeated addition (intentionally simple, not optimised).
- `Must` — panic helper so callers can write `money.Must(money.Sum(a, b))`.

---

### `validator/validator.go`

Uses the `go-playground/validator` library to validate HTTP form input before it is forwarded to backend services. Defined payload types:

- `AddToCartPayload` — validates `product_id` (non-empty) and `quantity` (1–10).
- `PlaceOrderPayload` — validates all checkout fields: email format, address fields, credit card number (luhn), expiry month/year, CVV.
- `SetCurrencyPayload` — validates that the submitted currency code is one of the whitelisted values.

`ValidationErrorResponse` converts `validator` errors into a human-readable error value returned to the browser as a 422 response.

---

### `genproto/`

Auto-generated from `demo.proto` (via `genproto.sh`). Contains the Go types and gRPC client/server interfaces for all backend services: `ProductCatalogService`, `CartService`, `CurrencyService`, `ShippingService`, `RecommendationService`, `CheckoutService`, and `AdService`. Do not edit these files manually.

---

### `templates/`

Go `html/template` files. All templates share common data injected by `injectCommonTemplateData` (session info, currency, platform, username, etc.). Custom template functions registered globally:

- `renderMoney` — formats money values for display.
- `renderCurrencyLogo` — returns the currency symbol.

---

### `static/`

Static files served under the `/static/` path prefix:

- `styles/` — CSS for cart, order, and chatbot pages.
- `icons/` — SVG icons (navigation logo, cart, social media, currency, etc.).
- `images/` — Hero banner, advert banners, and product photos.

---

## HTTP Routes

| Method | Path | Handler | Auth required |
|---|---|---|---|
| GET, HEAD | `/` | `homeHandler` | Yes |
| GET, HEAD | `/product/{id}` | `productHandler` | Yes |
| GET, HEAD | `/cart` | `viewCartHandler` | Yes |
| POST | `/cart` | `addToCartHandler` | Yes |
| POST | `/cart/empty` | `emptyCartHandler` | Yes |
| POST | `/cart/checkout` | `placeOrderHandler` | Yes |
| POST | `/setCurrency` | `setCurrencyHandler` | Yes |
| GET | `/logout` | `logoutHandler` | Yes |
| GET | `/assistant` | `assistantHandler` | Yes |
| POST | `/bot` | `chatBotHandler` | Yes |
| GET | `/product-meta/{ids}` | `getProductByID` | Yes |
| GET, POST | `/login` | `loginHandler` | No |
| GET, POST | `/register` | `registerHandler` | No |
| GET | `/_healthz` | inline (returns `ok`) | No |
| GET | `/robots.txt` | inline (disallows all) | No |
| GET | `/static/*` | `http.FileServer` | No |

> All paths are prefixed with `BASE_URL` if that environment variable is set.

---

## Middleware Stack

Requests pass through the following chain (outermost first):

```
OTel HTTP handler  ->  requireAuth  ->  ensureSessionID  ->  logHandler  ->  router
```

1. **OTel HTTP handler** (`otelhttp`) — creates a root span for each request and propagates trace context.
2. **`requireAuth`** — redirects unauthenticated users to `/login`.
3. **`ensureSessionID`** — assigns or reads the session ID cookie, stores it in context.
4. **`logHandler`** — attaches a request-scoped logger and logs timing/status on completion.

---

## Backend Service Connections

| Environment Variable | Protocol | Purpose |
|---|---|---|
| `PRODUCT_CATALOG_SERVICE_ADDR` | gRPC | Browse / fetch products |
| `CURRENCY_SERVICE_ADDR` | gRPC | List & convert currencies |
| `CART_SERVICE_ADDR` | gRPC | Read / write shopping cart |
| `RECOMMENDATION_SERVICE_ADDR` | gRPC | Product recommendations |
| `CHECKOUT_SERVICE_ADDR` | gRPC | Place orders |
| `SHIPPING_SERVICE_ADDR` | gRPC | Shipping cost quotes |
| `AD_SERVICE_ADDR` | gRPC | Contextual ads |
| `AUTH_SERVICE_ADDR` | HTTP | Login, register, token verify |
| `SHOPPING_ASSISTANT_SERVICE_ADDR` | HTTP | AI chatbot |
| `COLLECTOR_SERVICE_ADDR` | gRPC | OTel trace collector (when tracing enabled) |
| `PACKAGING_SERVICE_URL` | HTTP | Product dimensions (optional) |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP listen port |
| `LISTEN_ADDR` | `""` (all interfaces) | Bind address |
| `BASE_URL` | `""` | URL prefix for all routes |
| `ENABLE_TRACING` | `0` | Set to `1` to enable OTel tracing |
| `ENABLE_PROFILER` | `0` | Set to `1` to enable GCP Profiler |
| `ENABLE_SINGLE_SHARED_SESSION` | `false` | Use a fixed session ID for all users |
| `ENV_PLATFORM` | `local` | Platform hint (`local`, `gcp`, `aws`, `azure`, `onprem`, `alibaba`) |
| `CYMBAL_BRANDING` | `false` | Set to `true` to switch to Cymbal brand theme |
| `ENABLE_ASSISTANT` | `false` | Set to `true` to show the shopping assistant page |
| `FRONTEND_MESSAGE` | `""` | Optional banner message displayed on all pages |
| `BANNER_COLOR` | `""` | CSS color for the banner (canary deployment demo) |
| `PACKAGING_SERVICE_URL` | `""` | Base URL of the optional packaging microservice |

---

## Running Locally

> All backend services must be reachable before starting the frontend.

```bash
export PRODUCT_CATALOG_SERVICE_ADDR=localhost:3550
export CURRENCY_SERVICE_ADDR=localhost:7000
export CART_SERVICE_ADDR=localhost:7070
export RECOMMENDATION_SERVICE_ADDR=localhost:8082
export CHECKOUT_SERVICE_ADDR=localhost:5050
export SHIPPING_SERVICE_ADDR=localhost:50051
export AD_SERVICE_ADDR=localhost:9555
export AUTH_SERVICE_ADDR=localhost:8081
export SHOPPING_ASSISTANT_SERVICE_ADDR=localhost:8083

go run .
```

The server will start on `http://localhost:8080`.

---

## Dockerfile

The Dockerfile uses a **multi-stage build** to produce a tiny, secure production image.

```dockerfile
FROM golang:1.25.6-alpine AS builder
```
Stage 1 starts from the official Go 1.25.6 image on Alpine Linux (a minimal Linux distro). This stage is named `builder` so the second stage can copy from it. Alpine is used only for compilation — it never ships to production.

```dockerfile
WORKDIR /src
```
Sets the working directory inside the builder container to `/src`.

```dockerfile
COPY go.mod go.sum ./
RUN go mod download
```
Copies only the module files first and downloads all dependencies **before** copying source code. This is a **Docker layer caching optimisation** — if your Go source changes but `go.mod`/`go.sum` don't, Docker reuses the cached dependency layer and skips the download on the next rebuild.

```dockerfile
COPY . .
```
Copies the entire source code into `/src`.

```dockerfile
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o /go/bin/frontend .
```
Compiles the Go binary. The flags mean:
- `CGO_ENABLED=0` — disables C interop, producing a **fully static binary** with no external `.so` dependencies.
- `GOOS=linux GOARCH=amd64` — cross-compiles for Linux on 64-bit x86 (important if building on macOS or ARM).
- `-ldflags="-s -w"` — strips the symbol table (`-s`) and DWARF debug info (`-w`), making the binary significantly smaller.
- `-o /go/bin/frontend` — output path of the compiled binary.

---

```dockerfile
FROM gcr.io/distroless/static
```
Stage 2 starts a **brand new, minimal image** from Google's Distroless project. `distroless/static` contains only the bare minimum to run a statically-linked binary — no shell, no package manager, no utilities. This makes the final image very small and dramatically reduces the attack surface.

```dockerfile
WORKDIR /src
```
Sets the working directory in the final image.

```dockerfile
COPY --from=builder /go/bin/frontend /src/server
COPY ./templates ./templates
COPY ./static ./static
```
Copies only what is needed to run the app from the builder stage:
- The compiled binary → `/src/server`
- The `templates/` folder (HTML templates the server reads at runtime)
- The `static/` folder (CSS, images, icons served to the browser)

The entire Go toolchain and source code from Stage 1 are **discarded** — they never make it into the final image.

```dockerfile
ENV GOTRACEBACK=single
```
Configures Go's runtime crash behaviour. `single` means if the app panics, only the stack trace of the crashing goroutine is printed (not all goroutines). This is also used by **Skaffold's debug mode** to detect that this is a Go binary.

```dockerfile
EXPOSE 8080
```
Documents that the container listens on port 8080. This is informational — it does not actually open the port; you still need `-p 8080:8080` when running with `docker run`.

```dockerfile
ENTRYPOINT ["/src/server"]
```
Sets the compiled binary as the process that runs when the container starts.

---

### Why two stages?

| | Stage 1 (builder) | Stage 2 (runtime) |
|---|---|---|
| Base image | `golang:1.25.6-alpine` (~250 MB) | `distroless/static` (~2 MB) |
| Contains | Go compiler, source code, modules | Only the binary + templates + static files |
| Shipped to production? | No — discarded after build | Yes — this is the final image |

The result is a **tiny, secure production image** containing nothing except what the application needs to run.
