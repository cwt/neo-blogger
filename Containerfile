# Neo-Blogger production image (tech-req §15).
# Base: fedora:44 (same distro as the dev workstation, S5).
# Built and run rootless with Podman.

FROM fedora:44 AS build

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN dnf -y upgrade \
    && dnf -y install python3.14 python3.14-pip gcc sqlite-devel libicu-devel libicu zig \
    && dnf clean all

WORKDIR /build
COPY pyproject.toml README.md LICENSE THIRD-PARTY-LICENSES.md uv.lock ./
COPY neoblogger/ ./neoblogger/
RUN python3.14 -m pip install --no-cache-dir build hatchling \
    && python3.14 -m build --wheel --no-isolation --outdir /dist

# Compile the ICU tokenizer extension for Thai/CJK search (spec §12.2, §19.3).
# The .so copy is required (build fails without it); the header copy is
# best-effort for downstream builds and must not fail the image.
COPY tools/tokenizer/ /build/tokenizer/
WORKDIR /build/tokenizer
RUN zig build -Doptimize=ReleaseFast \
    && mkdir -p /out/lib \
    && cp zig-out/lib/libfts5_icu*.so /out/lib/
RUN mkdir -p /out/include && cp src/c_includes.h /out/include/ || true

FROM fedora:44 AS runtime

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN dnf -y upgrade \
    && dnf -y install python3.14 python3.14-pip libicu \
    && dnf clean all

COPY --from=build /out/lib/ /usr/local/lib/
COPY --from=build /dist/*.whl /tmp/wheel/
# Reproducible runtime install (tech-req §15.2): resolve every dependency
# from uv.lock pins. `uv export --frozen` emits the locked requirements
# (including the `serve` extra: gunicorn + uvicorn); the app wheel itself is
# installed with --no-deps so open-ended ranges in pyproject never resolve
# from PyPI at build time. The `uvicorn.workers.UvicornWorker` entrypoint
# ships inside the uvicorn package, so no separate `uvicorn-worker` install
# is needed. License attribution (§17.1) ships in /app/.
COPY uv.lock pyproject.toml README.md ./
RUN python3.14 -m pip install --no-cache-dir uv \
    && python3.14 -m uv export --frozen --no-dev --extra serve -o /tmp/requirements.txt \
    && python3.14 -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && python3.14 -m pip install --no-cache-dir --no-deps /tmp/wheel/*.whl \
    && rm -rf /tmp/wheel /tmp/requirements.txt uv.lock pyproject.toml README.md \
    && ldconfig

WORKDIR /app
COPY gunicorn.conf.py LICENSE THIRD-PARTY-LICENSES.md ./

# Database file and file-cache directory live on persistent storage (§19.2).
ENV NEOBLOGGER_CONFIG=/data/neo-blogger.toml
VOLUME ["/data"]
WORKDIR /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3.14 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

# The app is the only process; gunicorn manages uvicorn workers (§15.1, §15.3).
ENTRYPOINT ["gunicorn", "--config", "/app/gunicorn.conf.py", "neoblogger:create_app()"]
