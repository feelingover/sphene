FROM python:3.13-alpine AS builder

WORKDIR /app/

RUN python -m pip install --upgrade uv

COPY --link pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project --no-group dev

# --- ランナー用ステージ ---
FROM python:3.13-alpine AS runner

ARG USER_NAME=sphene
ARG USER_ID=1000
ARG GROUP_ID=${USER_ID}

RUN addgroup -S -g ${GROUP_ID} ${USER_NAME} \
    && adduser -u ${USER_ID} -G ${USER_NAME} -D ${USER_NAME}

WORKDIR /app/
COPY --from=builder /app/.venv /app/.venv
COPY --link . /app/

ENV PATH="/app/.venv/bin:$PATH"

USER ${USER_NAME}

CMD ["python", "app.py"]
