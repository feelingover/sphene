FROM python:3.13-alpine AS builder

ARG USER_NAME=sphene
ARG USER_ID=1000
ARG GROUP_ID=${USER_ID}

RUN addgroup -S -g ${GROUP_ID} ${USER_NAME} \
    && adduser -u ${USER_ID} -G ${USER_NAME} -D ${USER_NAME}

WORKDIR /app/
COPY --link requirements.txt requirements.txt
COPY --link requirements-dev.txt requirements-dev.txt

# rootユーザーのままuv/pipインストール
RUN python -m pip install --upgrade uv && \
    uv pip install --system -r requirements.txt

# --- ランナー用ステージ ---
FROM python:3.13-alpine AS runner

ARG USER_NAME=sphene
ARG USER_ID=1000
ARG GROUP_ID=${USER_ID}

RUN addgroup -S -g ${GROUP_ID} ${USER_NAME} \
    && adduser -u ${USER_ID} -G ${USER_NAME} -D ${USER_NAME}

WORKDIR /app/
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/requirements.txt requirements.txt
COPY --link . /app/

USER ${USER_NAME}

CMD ["python", "app.py"]
