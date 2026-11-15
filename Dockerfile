FROM python:3.12-slim

# WeasyPrint needs Pango; Noto fonts give proper Hindi / Marathi (Devanagari) and Gujarati in PDFs
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 \
        fonts-noto-core fonts-noto-ui-core fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tools ./tools
COPY examples ./examples

ENV TZ=Asia/Kolkata OUTPUT_DIR=/data/output
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
