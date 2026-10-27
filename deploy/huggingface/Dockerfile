# The LabScout web page and MCP server, as a Hugging Face Docker Space (port 7860, user 1000 as Spaces expect).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LABSCOUT_CACHE_DIR=/tmp/labscout-cache

RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY --chown=user pyproject.toml README.md LICENSE ./
COPY --chown=user src ./src
RUN pip install --no-cache-dir .

USER user
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health')"
CMD ["labscout", "serve", "--host", "0.0.0.0", "--port", "7860"]
