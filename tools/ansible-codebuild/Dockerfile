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

RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

COPY ansible/requirements.yml /tmp/ansible-requirements.yml
RUN ansible-galaxy collection install -r /tmp/ansible-requirements.yml

COPY ansible /workspace/ansible
COPY buildspec-ansible.yml /workspace/buildspec-ansible.yml

WORKDIR /workspace
