FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG TERRAFORM_DOCS_VERSION=0.24.0
ARG TRIVY_VERSION=0.76.1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# terraform-docs and trivy. Pin the versions above and rebuild to move forward.
RUN ARCH="$(dpkg --print-architecture)" \
    && case "${ARCH}" in \
         amd64) TF_ARCH="amd64"; TRIVY_ARCH="64bit" ;; \
         arm64) TF_ARCH="arm64"; TRIVY_ARCH="ARM64" ;; \
         *) echo "Unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/terraform-docs/terraform-docs/releases/download/v${TERRAFORM_DOCS_VERSION}/terraform-docs-v${TERRAFORM_DOCS_VERSION}-linux-${TF_ARCH}.tar.gz" \
         -o /tmp/terraform-docs.tar.gz \
    && tar -xzf /tmp/terraform-docs.tar.gz -C /usr/local/bin terraform-docs \
    && curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" \
         -o /tmp/trivy.tar.gz \
    && tar -xzf /tmp/trivy.tar.gz -C /usr/local/bin trivy \
    && rm /tmp/terraform-docs.tar.gz /tmp/trivy.tar.gz \
    && terraform-docs --version \
    && trivy --version

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# The uv image entrypoint is `uv`. The review command is plain Python.
ENTRYPOINT []
CMD ["python", "-m", "review"]
