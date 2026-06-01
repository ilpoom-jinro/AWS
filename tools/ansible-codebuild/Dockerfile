FROM public.ecr.aws/amazonlinux/amazonlinux:2023

ARG KUBECTL_VERSION=v1.35.0
ARG HELM_VERSION=v3.17.3
ARG ARGOCD_CHART_VERSION=""
ARG ISTIO_CHART_VERSION="1.30.0"

RUN dnf install -y \
      ca-certificates \
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

RUN mkdir -p /opt/helm-charts \
    && helm repo add argo https://argoproj.github.io/argo-helm \
    && helm repo add istio https://istio-release.storage.googleapis.com/charts \
    && helm repo update \
    && if [ -n "${ARGOCD_CHART_VERSION}" ]; then \
         helm pull argo/argo-cd --version "${ARGOCD_CHART_VERSION}" --untar --untardir /opt/helm-charts; \
       else \
         helm pull argo/argo-cd --untar --untardir /opt/helm-charts; \
       fi \
    && helm pull istio/base --version "${ISTIO_CHART_VERSION}" --untar --untardir /opt/helm-charts \
    && helm pull istio/istiod --version "${ISTIO_CHART_VERSION}" --untar --untardir /opt/helm-charts \
    && helm pull istio/cni --version "${ISTIO_CHART_VERSION}" --untar --untardir /opt/helm-charts \
    && helm pull istio/ztunnel --version "${ISTIO_CHART_VERSION}" --untar --untardir /opt/helm-charts \
    && test -f /opt/helm-charts/argo-cd/Chart.yaml \
    && test -f /opt/helm-charts/base/Chart.yaml \
    && test -f /opt/helm-charts/istiod/Chart.yaml \
    && test -f /opt/helm-charts/cni/Chart.yaml \
    && test -f /opt/helm-charts/ztunnel/Chart.yaml

COPY ansible/requirements.yml /tmp/ansible-requirements.yml
RUN ansible-galaxy collection install -r /tmp/ansible-requirements.yml

RUN aws --version \
    && kubectl version --client=true \
    && helm version --short \
    && git --version \
    && pkill --version

COPY ansible /workspace/ansible
COPY gitops /workspace/gitops
COPY buildspec-ansible.yml /workspace/buildspec-ansible.yml

WORKDIR /workspace
