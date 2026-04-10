FROM python:3.11-slim
WORKDIR /app
COPY agent /app/agent
CMD ["sh", "-c", "ls -la /app/agent && find /app/agent -maxdepth 2 -type d | sort"]
