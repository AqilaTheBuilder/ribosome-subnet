# Ribosome Network subnet - production neuron images
#
#   docker build -t ribosome-neuron .
#   docker compose up validator   # chaperone
#   docker compose up miner       # synthetase

FROM python:3.12-slim

# ViennaRNA for the physics-grade 2D oracle (optional but cheap here)
RUN apt-get update && apt-get install -y --no-install-recommends \
        viennarna curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ribosome/ ./ribosome/
COPY neurons/ ./neurons/
COPY simulation/ ./simulation/
COPY data/ ./data/

# RhoFold+ (optional GPU oracle): mount the repo + checkpoint at
#   /opt/rhofold  and  /opt/rhofold/RhoFold.pt
# and set RIBOSOME_RHOFOLD_REPO/RIBOSOME_RHOFOLD_CKPT accordingly.

ENV PYTHONUNBUFFERED=1

# default: validator; override command for the miner
CMD ["python", "neurons/validator.py", "--mode", "testnet"]
