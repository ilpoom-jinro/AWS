 pinned 2026-06-30, controlled bump via scheduled EOL workflow (#25)
FROM node:22.23.1-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

# pinned 2026-06-30, controlled bump via scheduled EOL workflow (#25)
FROM nginx:1.27.5-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
