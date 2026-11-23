FROM python:3.14-alpine AS builder

WORKDIR /app/

RUN python -m pip install --upgrade uv

COPY --link pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project --no-group dev

# --- ランナー用ステージ ---
FROM python:3.14-alpine AS runner

ARG USER_NAME=sphene
ARG USER_ID=1000
ARG GROUP_ID=${USER_ID}

RUN addgroup -S -g ${GROUP_ID} ${USER_NAME} \
    && adduser -u ${USER_ID} -G ${USER_NAME} -D ${USER_NAME}

WORKDIR /app/
COPY --from=builder /app/.venv /app/.venv
COPY --link . /app/

# STORAGE_TYPE=local のデータ（チャンネル設定・記憶ストア）は /app/storage に書き込む。
# ソースは root 所有のまま、書き込み先だけ実行ユーザーの所有にする。
# .dockerignore で storage/ はイメージに含めないため、ここで作成する
RUN mkdir -p /app/storage && chown ${USER_ID}:${GROUP_ID} /app/storage
# 再起動・再作成でデータが消えないよう、ボリュームのマウント先として宣言する
VOLUME ["/app/storage"]

ENV PATH="/app/.venv/bin:$PATH"

USER ${USER_NAME}

CMD ["python", "app.py"]
