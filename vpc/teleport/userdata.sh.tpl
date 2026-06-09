#!/bin/bash
set -e
LOG="/var/log/teleport-init.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== Teleport 초기화 시작: $(date) ==="

# ── 1. IP Forwarding 활성화 ─────────────────────────────────────────────────
sysctl -p /etc/sysctl.d/99-teleport.conf

# ── 2. K3s 시작 ────────────────────────────────────────────────────────────
systemctl enable k3s
systemctl start k3s || true  # K3s 시작 실패해도 스크립트 계속 진행 (타이밍 이슈 방지)
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
  tokens:
    - "app:${teleport_app_join_token}"
proxy_service:
  enabled: yes
  web_listen_addr: 0.0.0.0:3080
  tunnel_listen_addr: 0.0.0.0:3024
  public_addr: localhost:3080
  ssh_public_addr: localhost:3080
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

# ── 6. EFS 마운트 (/var/lib/teleport) ──────────────────────────────────────
mkdir -p /var/lib/teleport
mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport ${efs_dns}:/ /var/lib/teleport
echo "${efs_dns}:/ /var/lib/teleport nfs4 nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport,_netdev 0 0" >> /etc/fstab
echo "EFS 마운트 완료"

# ── 7. Teleport 시작 ────────────────────────────────────────────────────────
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

# ── 8. kube-access role 생성 ───────────────────────────────────────────────
tctl create -f << 'ROLEEOF' 2>&1 || echo "kube-access role 이미 존재"
kind: role
version: v7
metadata:
  name: kube-access
spec:
  allow:
    kubernetes_groups:
      - system:masters
    kubernetes_labels:
      '*': '*'
    kubernetes_resources:
      - kind: '*'
        namespace: '*'
        name: '*'
        verbs:
          - '*'
ROLEEOF
echo "kube-access role 설정 완료"

tctl create -f << 'APPROLEEOF' 2>&1 || echo "mas-ui-access role 이미 존재"
kind: role
version: v7
metadata:
  name: mas-ui-access
spec:
  allow:
    app_labels:
      type: mas-ui
APPROLEEOF
echo "mas-ui-access role 설정 완료"

# ── 9. Teleport 유저 생성 ───────────────────────────────────────────────────
echo "=== Teleport 유저 invite 링크 ==="
tctl users add bgshin     --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 신봉근
tctl users add junho      --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 백준호
tctl users add junyounglee --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 이준영
tctl users add dahyeon    --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 조다현
tctl users add sangjun    --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 허상준
tctl users add gyeonghan  --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 김경한
tctl users add minsu      --roles=editor,access,kube-access,mas-ui-access --logins=root,ubuntu --ttl=48h 2>&1 || echo "유저 이미 존재" # 김민수
echo "=== 초기화 완료: $(date) ==="
echo "로그 확인: cat /var/log/teleport-init.log | grep -A2 'invite'"
