# syntax=docker/dockerfile:1

FROM node:20-alpine AS deps
WORKDIR /app
# Copiamos solo los manifests válidos (sin hacks de shell)
COPY package*.json ./
RUN npm i --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Genera Prisma y compila TypeScript
ENV DATABASE_URL="postgresql://bd_bbxback_user:362pZuxhYkMzfRsQ6GBcJx9w2wTqD3T0@dpg-d2r18aumcj7s73cmtav0-a/bd_bbxback"
RUN npx prisma generate && npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV DATABASE_URL="postgresql://bd_bbxback_user:362pZuxhYkMzfRsQ6GBcJx9w2wTqD3T0@dpg-d2r18aumcj7s73cmtav0-a/bd_bbxback"
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/package.json ./package.json
# Puedes copiar .env.example si quieres tener referencia en el contenedor
# COPY --from=builder /app/.env.example ./.env
EXPOSE 8080
CMD ["node", "dist/index.js"]