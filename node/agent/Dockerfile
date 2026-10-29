FROM python:3.12-alpine
# openssl: the agent creates its self-signed certificate on first start
RUN apk add --no-cache openssl
WORKDIR /agent
COPY agent.py ./
EXPOSE 7443
CMD ["python", "-u", "agent.py"]
