FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir mysql-connector-python==9.7.0
COPY migration_runner.py .
COPY migrations ./migrations
CMD ["python", "migration_runner.py"]
