FROM node:20-bookworm-slim

ENV NODE_ENV=production \
    PORT=10000 \
    PYTHON=python3 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY frontend/package*.json ./frontend/
WORKDIR /app/frontend
RUN npm ci

WORKDIR /app
COPY . .

WORKDIR /app/frontend
RUN npm run build

EXPOSE 10000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "10000"]
