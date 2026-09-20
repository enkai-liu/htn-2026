# The API for Railway (or any container host). Build context is backend/.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# /srv/backend, not /app: app/config.py takes the repo root as two levels above the package and puts data/ there
WORKDIR /srv/backend
COPY pyproject.toml ./
COPY app ./app
COPY fixtures ./fixtures
# editable on purpose: config.py finds fixtures/ and runs/ relative to the source tree, not site-packages
RUN pip install -e .
# shell form so $PORT, which the host assigns, is expanded
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
