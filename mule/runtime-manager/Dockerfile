FROM python:3.12-alpine
WORKDIR /app
# cryptography: Fernet for secure properties at rest (the only dependency; everything else is stdlib)
RUN pip install --no-cache-dir cryptography==50.0.2
COPY app.py pools.py index.html login.html docs.html openapi.json ./
EXPOSE 8080
CMD ["python", "-u", "app.py"]
