# Single-image deploy: builds the React dashboard, the DuckDB from sample data,
# and serves both from one FastAPI/uvicorn process. One repo, one service.

# ---- Stage 1: build the React dashboard ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY deterioration-detector/frontend/package*.json ./
RUN npm install
COPY deterioration-detector/frontend/ ./
RUN npm run build

# ---- Stage 2: Python API + data pipeline ----
FROM python:3.13-slim
WORKDIR /app

COPY deterioration-detector/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY deterioration-detector/ ./

# Bake the DuckDB at build time from the committed synthetic sample so the
# running container reads an immutable, ready-to-serve database (fast cold start).
RUN python scripts/generate_sample_data.py \
 && python scripts/build_db.py \
 && python scripts/build_risk.py

# Bring in the compiled frontend so FastAPI can serve it at /
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
