FROM python:3.12-alpine
WORKDIR /app
# cryptography: Fernet for the S3 secret keys at rest (the only dependency; everything else is stdlib)
RUN pip install --no-cache-dir cryptography==50.0.2
COPY archiver.py app.py index.html ./
EXPOSE 8080
CMD ["python", "-u", "app.py"]
