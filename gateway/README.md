# API Gateway

Reserved. The gateway product is decision **T2** and has not been made.

Until then, services are reached directly on their local ports (8001–8008) and the React
dev server proxies `/svc/<service>` for local development only. Every service already
handles correlation IDs, the error model and health checks itself, so it will work behind
whichever gateway is chosen.
