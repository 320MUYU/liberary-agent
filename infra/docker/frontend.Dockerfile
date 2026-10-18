FROM node:24-bookworm-slim AS build
WORKDIR /build
COPY vue-project/package.json vue-project/package-lock.json ./
RUN npm ci
COPY vue-project/ ./
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM nginx:1.28-alpine
ENV TZ=Asia/Shanghai
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
