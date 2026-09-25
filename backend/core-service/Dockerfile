FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY backend/core-service/package*.json ./
RUN npm ci --no-audit --no-fund
COPY backend/core-service/tsconfig*.json ./
COPY backend/core-service/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:24-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY backend/core-service/openapi.json ./openapi.json
USER node
EXPOSE 8000
CMD ["node", "dist/main.js"]
