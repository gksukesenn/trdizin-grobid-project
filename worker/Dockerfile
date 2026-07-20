FROM python:3.12-slim

WORKDIR /app

COPY processor/requirements.txt /tmp/processor-requirements.txt
COPY database/importer/requirements.txt /tmp/importer-requirements.txt

RUN pip install --no-cache-dir \
    -r /tmp/processor-requirements.txt \
    -r /tmp/importer-requirements.txt

COPY processor/process_pdfs.py /app/process_pdfs.py
COPY database/importer/import_grobid.py /app/import_grobid.py
COPY worker/run_pipeline.py /app/run_pipeline.py

CMD ["python", "/app/run_pipeline.py"]
