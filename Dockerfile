FROM python:3.12-alpine3.21

COPY --link . /app/
WORKDIR /app/
RUN pip install -r requirements.txt

CMD ["python", "app.py"]