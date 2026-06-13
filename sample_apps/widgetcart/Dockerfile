# WidgetCart — minimal Node image. No npm install (zero dependencies), so the
# build is instant and the container comes up immediately.
FROM node:20-alpine
WORKDIR /app
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["node", "server.js"]
