# Build context: deploy_tenant/ (parent of admin-service)
# So COPY paths are relative to deploy_tenant/

FROM python:3.12-slim

ENV TZ=Asia/Shanghai

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* && apt-get clean

WORKDIR /app

COPY admin-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY admin-service /app/admin-service
RUN mkdir -p /app/data

WORKDIR /app/admin-service

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
