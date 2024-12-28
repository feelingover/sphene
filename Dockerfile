FROM python:3.12-alpine3.21

ARG USER_NAME=sphene
ARG USER_ID=1000
ARG GROUP_ID=$UID

RUN <<EOF
  addgroup -S -g "${GROUP_ID}" "${USER_NAME}"
  adduser -u "${USER_ID}" -G "${USER_NAME}" -D "${USER_NAME}"
EOF

USER "${USER_NAME}"

COPY --link . /app/
WORKDIR /app/

RUN <<EOF
  pip install --user --upgrade pip
  pip install --user --upgrade setuptools
  pip install --user -r requirements.txt
EOF

ENV PYTHONUSERBASE=/home/$USERNAME/.local PATH=$PYTHONUSERBASE/bin:$PATH

CMD ["python", "app.py"]