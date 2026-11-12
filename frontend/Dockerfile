# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS build
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /frontend/dist /usr/share/nginx/html
ENV HATCH_API_UPSTREAM=http://orchestrator:8000
EXPOSE 8080
