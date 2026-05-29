#!/bin/bash
set -e
LOG="/var/log/teleport-init.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Teleport 초기화 시작: $(date) ==="

# ── 1. IP Forwarding 활성화 ─────────────────────────────────────────────────
sysctl -p /etc/sysctl.d/99-teleport.conf

# ── 2. K3s 시작 ────────────────────────────────────────────────────────────
systemctl enable k3s
systemctl start k3s
until kubectl get nodes 2>/dev/null | grep -q Ready; do
  echo "K3s 준비 대기중..."
  sleep 5
done
echo "K3s 준비 완료"

# ── 3. kubeconfig 생성 (EKS) ───────────────────────────────────────────────
mkdir -p /root/.kube
cat > /root/.kube/config << 'KUBEEOF'
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${eks_ca_data}
    server: ${eks_endpoint}
  name: financial-ops-eks
contexts:
- context:
    cluster: financial-ops-eks
    user: teleport-kube
  name: financial-ops-eks
current-context: financial-ops-eks
users:
- name: teleport-kube
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: /usr/local/bin/aws-iam-authenticator
      args:
        - token
        - -i
        - financial-ops-eks
KUBEEOF
chmod 600 /root/.kube/config
echo "kubeconfig 생성 완료"

# ── 4. Teleport 설정 ────────────────────────────────────────────────────────
cat > /etc/teleport.yaml << 'TELEEOF'
version: v3
teleport:
  nodename: financial-teleport
  data_dir: /var/lib/teleport
  log:
    output: /var/log/teleport.log
    severity: INFO
auth_service:
  enabled: yes
  listen_addr: 0.0.0.0:3025
  cluster_name: financial-teleport
proxy_service:
  enabled: yes
  web_listen_addr: 0.0.0.0:3080
  tunnel_listen_addr: 0.0.0.0:3024
  public_addr: localhost:3080
  kube_listen_addr: 0.0.0.0:3026
ssh_service:
  enabled: no
kubernetes_service:
  enabled: yes
  listen_addr: 0.0.0.0:3027
  kubeconfig_file: /root/.kube/config
TELEEOF
echo "teleport.yaml 생성 완료"

# ── 5. systemd PATH override ────────────────────────────────────────────────
mkdir -p /etc/systemd/system/teleport.service.d/
cat > /etc/systemd/system/teleport.service.d/override.conf << 'SVCEOF'
[Service]
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
SVCEOF

# ── 6. Teleport 시작 ────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable teleport
systemctl start teleport

echo "Teleport 시작 대기중..."
for i in $(seq 1 60); do
  if tctl status 2>/dev/null | grep -q "Cluster"; then
    echo "Teleport 준비 완료"
    break
  fi
  echo "대기 중... ($i/60)"
  sleep 5
done

# ── 7. Teleport 유저 생성 ───────────────────────────────────────────────────
echo "=== Teleport 유저 invite 링크 ==="
tctl users add bgshin --roles=editor,access --logins=root,ubuntu 2>&1 || echo "유저 이미 존재"
echo "=== 초기화 완료: $(date) ==="
echo "로그 확인: cat /var/log/teleport-init.log | grep -A2 'invite'"
