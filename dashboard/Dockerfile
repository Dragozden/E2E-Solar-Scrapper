# Streamlit application image. This image contains NO credentials or writable DB logic.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    HOME=/home/dashboard

WORKDIR /app

RUN groupadd --system dashboard && \
    useradd --system --uid 10001 --gid dashboard --create-home --home-dir /home/dashboard dashboard

COPY dashboard/requirements-docker.txt /tmp/requirements-docker.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-docker.txt

COPY --chown=dashboard:dashboard dashboard/ /app/dashboard/

USER dashboard
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["python", "-m", "streamlit", "run", "dashboard/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
