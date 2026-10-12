# Neo-Blogger production image (tech-req §15).
# Base: fedora:44 (same distro as the dev workstation, S5).
# Built and run rootless with Podman.

FROM fedora:44 AS build

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN dnf -y upgrade \
    && dnf -y install python3.14 python3.14-pip gcc sqlite-devel libicu-devel libicu zig \
    && dnf clean all

WORKDIR /build
COPY pyproject.toml README.md LICENSE uv.lock ./
COPY neoblogger/ ./neoblogger/
RUN python3.14 -m pip install --no-cache-dir build hatchling \
    && python3.14 -m build --wheel --no-isolation --outdir /dist

# Compile the ICU tokenizer extension for Thai/CJK search (spec §12.2, §19.3).
COPY tools/tokenizer/ /build/tokenizer/
WORKDIR /build/tokenizer
RUN zig build -Doptimize=ReleaseFast \
    && mkdir -p /out/lib \
    && cp zig-out/lib/libfts5_icu*.so /out/lib/ \
    && mkdir -p /out/include && cp src/c_includes.h /out/include/ || true

FROM fedora:44 AS runtime

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN dnf -y upgrade \
    && dnf -y install python3.14 python3.14-pip libicu \
    && dnf clean all

COPY --from=build /out/lib/ /usr/local/lib/
COPY --from=build /dist/*.whl /tmp/wheel/
RUN python3.14 -m pip install --no-cache-dir \
        gunicorn "uvicorn[standard]>=0.34" uvicorn-worker \
    && python3.14 -m pip install --no-cache-dir /tmp/wheel/*.whl \
    && rm -rf /tmp/wheel \
    && ldconfig

WORKDIR /app
COPY gunicorn.conf.py ./

# Database file and file-cache directory live on persistent storage (§19.2).
ENV NEOBLOGGER_CONFIG=/data/neo-blogger.toml
VOLUME ["/data"]
WORKDIR /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3.14 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

# The app is the only process; gunicorn manages uvicorn workers (§15.1, §15.3).
ENTRYPOINT ["gunicorn", "--config", "/app/gunicorn.conf.py", "neoblogger:create_app()"]
