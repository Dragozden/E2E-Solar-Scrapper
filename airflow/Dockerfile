# Local development Airflow image; not a production deployment.
FROM apache/airflow:3.3.2-python3.12

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Separate environment keeps dbt and Playwright dependencies from altering Airflow's environment.
USER airflow
RUN python -m venv /opt/airflow/solar-venv \
    && /opt/airflow/solar-venv/bin/python -m pip install --no-cache-dir \
       'playwright>=1.56,<2' \
       'psycopg[binary]>=3.2,<4' \
       'python-dotenv>=1,<2' \
       'beautifulsoup4>=4.12,<5' \
       'lxml>=5,<7' \
       'pandas>=2.2,<4' \
       'dbt-postgres>=1.10,<2'

# Install browser and Linux system libraries at image build time.
USER root
RUN /opt/airflow/solar-venv/bin/python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && mkdir -p /opt/airflow/state \
    && chown -R airflow:0 /opt/airflow/state

USER airflow
