FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y \
      findutils \
      git \
      gzip \
      python3 \
      python3-pip \
      tar \
      unzip \
      which \
    && dnf clean all

RUN pip3 install --no-cache-dir \
      ansible \
      boto3 \
      botocore \
      kubernetes \
      openshift \
      PyYAML

RUN curl -Lo /usr/local/bin/kubectl \
      https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl \
    && chmod +x /usr/local/bin/kubectl

ARG HELM_VERSION=v3.17.3
RUN curl -fsSLo /tmp/helm.tar.gz \
      "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm \
    && rm -rf /tmp/helm.tar.gz /tmp/linux-amd64

COPY ansible/requirements.yml /tmp/ansible-requirements.yml
RUN ansible-galaxy collection install -r /tmp/ansible-requirements.yml

COPY ansible /workspace/ansible
COPY buildspec-ansible.yml /workspace/buildspec-ansible.yml

WORKDIR /workspace
