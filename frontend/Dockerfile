# HRMS frontend (docs/HRMS_COMPLETE_SPEC.txt Part 13 section A): static build served by
# nginx, which also reverse-proxies /_api/* to the api service on the SAME origin -- so the
# browser's Host header (the tenant subdomain / custom domain) reaches the API unchanged
# and TenantResolverMiddleware resolves the right tenant.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=/_api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://localhost:8080/nginx-health || exit 1
