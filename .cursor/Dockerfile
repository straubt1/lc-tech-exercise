FROM ubuntu:24.04

ARG TERRAFORM_VERSION=1.16.6
ARG MINISTACK_VERSION=1.5.29

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/home/ubuntu/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Terraform (multi-arch). Pin TERRAFORM_VERSION and rebuild to move forward.
RUN ARCH="$(dpkg --print-architecture)" \
    && case "${ARCH}" in \
      amd64) TF_ARCH="amd64" ;; \
      arm64) TF_ARCH="arm64" ;; \
      *) echo "Unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip" \
      -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm /tmp/terraform.zip \
    && terraform version

# MiniStack. Pin MINISTACK_VERSION and rebuild to move forward.
RUN pip3 install --no-cache-dir --break-system-packages \
    "ministack==${MINISTACK_VERSION}" \
    && python3 -c "import importlib.metadata as m; print('ministack', m.version('ministack'))"

# uv (Python deps for release.terraform_module_releaser). Install to /usr/local/bin so login-shell install finds it.
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
    && uv --version

# Cloud Agent requires git and a non-root ubuntu user with passwordless sudo.
RUN id -u ubuntu &>/dev/null || useradd -m -s /bin/bash ubuntu \
    && usermod -aG sudo ubuntu \
    && echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu

USER ubuntu
WORKDIR /home/ubuntu
