FROM public.ecr.aws/amazonlinux/amazonlinux:2023

ARG KUBECTL_VERSION=v1.35.0
ARG HELM_VERSION=v3.17.3

RUN dnf install -y \
      ca-certificates \
      curl \
      findutils \
      git \
      gzip \
      procps-ng \
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
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl

RUN curl -fsSLo /tmp/awscliv2.zip \
      https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip

RUN curl -fsSLo /tmp/helm.tar.gz \
      "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm \
    && rm -rf /tmp/helm.tar.gz /tmp/linux-amd64

COPY ansible/requirements.yml /tmp/ansible-requirements.yml
RUN ansible-galaxy collection install -r /tmp/ansible-requirements.yml

RUN aws --version \
    && kubectl version --client=true \
    && helm version --short \
    && git --version \
    && pkill --version

COPY ansible /workspace/ansible
COPY buildspec-ansible.yml /workspace/buildspec-ansible.yml

WORKDIR /workspace
