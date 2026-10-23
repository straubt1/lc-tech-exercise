FROM node:22-alpine

# Polling picks up laptop edits through the ArcBox bind mount, where inotify
# events from the host do not always arrive.
ENV CHOKIDAR_USEPOLLING=true \
    CHOKIDAR_INTERVAL=200

WORKDIR /site

RUN npm install -g live-server@1.2.2

COPY index.html ./
COPY assets ./assets

EXPOSE 80

CMD ["live-server", "--port=80", "--host=0.0.0.0", "--no-browser", "--watch=index.html,assets"]
