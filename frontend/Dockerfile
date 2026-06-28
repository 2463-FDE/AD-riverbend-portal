FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
# Internal gateway URL must be present at build time too: Next can constant-fold
# process.env into the standalone bundle, so an unset value bakes the localhost
# fallback. Compose still overrides this at runtime.
ENV GATEWAY_URL=http://gateway:8070
RUN npm run build

EXPOSE 3070
CMD ["npm", "run", "start"]
