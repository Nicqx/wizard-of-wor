# x86_64 NUC target. Compiles only the open-source libretro VICE core, not games.
FROM debian:bookworm-slim AS vice-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential pkg-config zlib1g-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*
ARG VICE_SHA=f63b56688f3133a2bb17499db9eebb7ab81df5f5
WORKDIR /build
RUN git clone https://github.com/libretro/vice-libretro.git vice && \
    cd vice && git checkout "$VICE_SHA" && make -j2 EMUTYPE=x64 && \
    test -s vice_x64_libretro.so

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 zlib1g libpng16-16 && rm -rf /var/lib/apt/lists/*
COPY --from=vice-builder /build/vice/vice_x64_libretro.so /opt/vice/vice_x64_libretro.so
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY web ./web
ENV PYTHONUNBUFFERED=1 PORT=8107 \
    GAME_D64=/games/game.d64 VICE_CORE_PATH=/opt/vice/vice_x64_libretro.so \
    VICE_SYSTEM_DIR=/tmp/vice MAX_ROOMS=4
RUN mkdir -p /games /tmp/vice && chown -R 10001:10001 /app /tmp/vice /games
USER 10001:10001
EXPOSE 8107
HEALTHCHECK --interval=20s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8107/healthz',timeout=3)"
CMD ["python","-m","server.app"]
