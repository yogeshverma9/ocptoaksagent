FROM python:3.12-slim

ARG HELM_VERSION=v3.16.3
ARG KUBECONFORM_VERSION=v0.6.7
ARG CONFTEST_VERSION=0.56.0
ARG TRIVY_VERSION=0.74.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git tar gzip \
    && rm -rf /var/lib/apt/lists/*

# helm
RUN curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
      | tar -xz -C /tmp \
    && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm

# kubeconform
RUN curl -fsSL "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" \
      | tar -xz -C /tmp \
    && mv /tmp/kubeconform /usr/local/bin/kubeconform \
    && chmod +x /usr/local/bin/kubeconform

# conftest
RUN curl -fsSL "https://github.com/open-policy-agent/conftest/releases/download/v${CONFTEST_VERSION}/conftest_${CONFTEST_VERSION}_Linux_x86_64.tar.gz" \
      | tar -xz -C /tmp \
    && mv /tmp/conftest /usr/local/bin/conftest \
    && chmod +x /usr/local/bin/conftest

# trivy
RUN curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
      | tar -xz -C /tmp \
    && mv /tmp/trivy /usr/local/bin/trivy \
    && chmod +x /usr/local/bin/trivy

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src
COPY config /app/config
COPY policy /app/policy

ENV PYTHONPATH=/app/src \
    AKSMIG_CONFIG_DIR=/config \
    AKSMIG_DEFAULT_CONFIG_DIR=/app/config \
    AKSMIG_POLICY_DIR=/app/policy

RUN useradd -u 10001 -m agent && mkdir -p /workspace /aks && chown -R agent /workspace /aks
USER 10001

ENTRYPOINT ["python", "-m", "aksmig"]
CMD ["--help"]