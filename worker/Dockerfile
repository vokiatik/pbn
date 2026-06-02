FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		libgl1 \
		libglib2.0-0 \
		libsm6 \
		libxext6 \
		libxrender1 \
		libxcb1 \
	&& rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /app/worker-requirements.txt
RUN pip install --no-cache-dir -r /app/worker-requirements.txt

COPY requirements.txt /app/base-requirements.txt
RUN pip install --no-cache-dir -r /app/base-requirements.txt

COPY . /app

WORKDIR /app
ENV PYTHONPATH=/app
CMD ["python", "-m", "worker.worker"]
