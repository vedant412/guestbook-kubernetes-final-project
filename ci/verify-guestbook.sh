#!/usr/bin/env bash
set -euo pipefail

ROOT="$PWD"
OUT="$ROOT/verification-evidence"
mkdir -p "$OUT"
cat > "$OUT/ENVIRONMENT.txt" <<'EOF'
Actual Docker and Kubernetes execution in a temporary kind cluster on GitHub Actions.
The registry for the Docker push is private to the runner and addressed at localhost.
IBM Cloud Container Registry output for Question 2 remains specific to the course lab.
EOF

capture() {
  local file="$1"
  shift
  {
    printf '$'
    printf ' %q' "$@"
    printf '\n'
    "$@"
  } 2>&1 | tee "$OUT/$file.txt"
}

stage=$(mktemp -d)
cp -R v1/guestbook "$stage/v2"
cp versions/v2/index.html "$stage/v2/public/index.html"
docker build --tag guestbook:v1 v1/guestbook
docker build --tag guestbook:v2 "$stage/v2"

docker run -d -p 127.0.0.1:5000:5000 --name guestbook-registry registry:2
for i in $(seq 1 15); do
  if curl --fail --silent http://127.0.0.1:5000/v2/ >/dev/null; then
    break
  fi
  sleep 1
done
docker tag guestbook:v2 localhost:5000/guestbook:v2
capture upguestbook-local docker push localhost:5000/guestbook:v2
grep -Eq 'digest: sha256:[0-9a-f]{64}' "$OUT/upguestbook-local.txt"

curl --fail --silent --show-error --location --retry 3 \
  https://kind.sigs.k8s.io/dl/v0.33.0/kind-linux-amd64 --output "$stage/kind"
chmod +x "$stage/kind"
kind="$stage/kind"
"$kind" create cluster --name guestbook-verification --wait 120s
"$kind" load docker-image guestbook:v1 guestbook:v2 --name guestbook-verification

kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.0/components.yaml
# kind uses a self-signed kubelet certificate in this isolated test cluster.
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl -n kube-system rollout status deployment/metrics-server --timeout=150s

kubectl create namespace guestbook-verify
kubectl config set-context --current --namespace=guestbook-verify
kubectl create -f kubernetes/hpa.yml
capture hpa kubectl get hpa guestbook
kubectl apply -f kubernetes/service.yml

render_deployment() {
  local source="$1"
  local tag="$2"
  sed -e "s|GUESTBOOK_IMAGE|guestbook:$tag|" -e "s|imagePullPolicy: Always|imagePullPolicy: IfNotPresent|" \
    "$source" > deployment.yml
}

render_deployment v1/guestbook/deployment.yml v1
kubectl apply -f deployment.yml
kubectl rollout status deployment/guestbook --timeout=120s
first_revision=$(kubectl get deployment guestbook -o 'jsonpath={.metadata.annotations.deployment\.kubernetes\.io/revision}')

job=$(kubectl create -f kubernetes/load.yml -o name)
scaled=false
for i in $(seq 1 30); do
  replicas=$(kubectl get hpa guestbook -o 'jsonpath={.status.currentReplicas}')
  if [[ "$replicas" =~ ^[0-9]+$ ]] && (( replicas > 1 )); then
    capture hpa2 kubectl get hpa guestbook
    scaled=true
    break
  fi
  sleep 7
done
kubectl delete "$job" --ignore-not-found --wait=false
if [ "$scaled" != true ]; then
  kubectl describe hpa guestbook
fi

kubectl delete hpa guestbook
kubectl scale deployment guestbook --replicas=1
kubectl rollout status deployment/guestbook --timeout=120s
render_deployment versions/v2/deployment.yml v2
capture deployment kubectl apply -f deployment.yml
kubectl rollout status deployment/guestbook --timeout=120s
second_revision=$(kubectl get deployment guestbook -o 'jsonpath={.metadata.annotations.deployment\.kubernetes\.io/revision}')

{
  echo '$ kubectl rollout history deployment/guestbook'
  kubectl rollout history deployment/guestbook
  echo "\$ kubectl rollout history deployment/guestbook --revision=$first_revision"
  kubectl rollout history deployment/guestbook --revision="$first_revision"
  echo "\$ kubectl rollout history deployment/guestbook --revision=$second_revision"
  kubectl rollout history deployment/guestbook --revision="$second_revision"
} | tee "$OUT/rev.txt"
grep -Eq 'cpu:[[:space:]]*20m' "$OUT/rev.txt"
grep -Eq 'cpu:[[:space:]]*2m' "$OUT/rev.txt"

kubectl rollout undo deployment/guestbook --to-revision="$first_revision"
kubectl rollout status deployment/guestbook --timeout=120s
test "$(kubectl get deployment guestbook -o 'jsonpath={.spec.template.spec.containers[0].image}')" = guestbook:v1
capture rs kubectl get rs
test "$(kubectl get rs -o name | wc -l)" -eq 2
test "$scaled" = true
