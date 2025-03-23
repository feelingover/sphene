FROM python:3.13-alpine

ARG USER_NAME=sphene
ARG USER_ID=1000
ARG GROUP_ID=${USER_ID}

RUN <<EOF
  addgroup -S -g ${GROUP_ID} ${USER_NAME}
  adduser -u ${USER_ID} -G ${USER_NAME} -D ${USER_NAME}
  
EOF

USER "${USER_NAME}"

COPY --link . /app/
WORKDIR /app/

RUN <<EOF
  pip install --user --upgrade pip
  pip install --user --upgrade setuptools
  pip install --user -r requirements.txt
EOF

CMD ["python", "app.py"]