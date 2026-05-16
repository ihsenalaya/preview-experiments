# Setup AKS — Reproducible Installation Guide

End-to-end recipe for running the preview-operator experimental harness on Azure
Kubernetes Service. Includes every gotcha discovered during the 2026-05-16 migration
from local Kind to AKS so the install can be reproduced without improvisation.

## Why AKS instead of Kind

Kind on WSL2 is fine for small runs but limited to ~7.7 GB RAM and a single node.
The harness has five experiments (RQ1–RQ5) × five subjects; the sequential local
run estimate is ~44 h. AKS lets us parallelize per-subject and bring it down to
~2 h wall clock. The trade-off is a more complex setup (GHCR pull-secret race,
image build-and-push instead of `kind load`, etc.) documented below.

---

## 0. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Azure CLI (`az`) | 2.75+ | Authenticated; subscription has Contributor on target RG |
| kubectl | 1.29+ | |
| helm | 3.14+ | |
| docker | 24+ | Docker Desktop on Windows with WSL integration enabled |
| git | any | |
| gh CLI | 2.0+ | PAT with `repo` + `write:packages` scopes |
| Python | 3.10+ | For the orchestrator on PC |

WSL2 specific:
- Verify Docker Desktop's WSL integration: in Docker Desktop → Settings → Resources → WSL Integration, enable the distro.
- The Linux `docker` binary should reach the Docker Desktop daemon at `/var/run/docker.sock`.
- Run `docker info` from inside WSL; the output should show ServerVersion. If it errors with "could not be found", restart Docker Desktop and re-enable integration.

---

## 1. AKS cluster

```bash
RG=idp-preview-rg
CLUSTER=idp-preview-cluster
LOCATION=eastus

az group create --name "$RG" --location "$LOCATION"

az aks create \
  --resource-group "$RG" \
  --name "$CLUSTER" \
  --location "$LOCATION" \
  --tier free \
  --node-count 2 \
  --node-vm-size Standard_D4s_v3 \
  --generate-ssh-keys
```

Notes:
- `--tier free` makes the control plane free (no SLA). Nodes are billed as usual.
- `Standard_D4s_v3` = 4 vCPU, 16 GB RAM per node. 2 nodes = 8 vCPU, 32 GB total. Sufficient for ~10 concurrent Previews at the `medium` resource tier.
- Default quota is 20 vCPU per family in `eastus`. If a previous failed cluster still has VMSS in `MC_*` RG, delete it first to free quota.

### Merge kubeconfig (WSL-safe)

`az aks get-credentials --file ~/.kube/config` writes a Windows-style path on WSL that `kubectl` cannot read. Use this pipeline instead:

```bash
mkdir -p "$HOME/.kube"; touch "$HOME/.kube/config"

az aks get-credentials --resource-group "$RG" --name "$CLUSTER" --file - \
  | KUBECONFIG="$HOME/.kube/config":/dev/stdin \
    kubectl config view --merge --flatten \
  > /tmp/merged-kube \
  && mv /tmp/merged-kube "$HOME/.kube/config"

kubectl config use-context "$CLUSTER"
kubectl get nodes
```

---

## 2. Helm repositories

```bash
helm repo add jetstack       https://charts.jetstack.io
helm repo add ingress-nginx  https://kubernetes.github.io/ingress-nginx
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo add microcks       https://microcks.io/helm
helm repo update
```

---

## 3. Cluster components

Install in this order — each step depends on the previous one.

### 3.1 cert-manager

Required by the operator's admission webhook and by the OpenTelemetry Operator.

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version v1.20.2 \
  --set crds.enabled=true \
  --wait

kubectl -n cert-manager rollout status deployment/cert-manager --timeout=120s
kubectl -n cert-manager rollout status deployment/cert-manager-webhook --timeout=120s
```

### 3.2 ingress-nginx

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --wait

kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s
```

Record the LoadBalancer IP for later (Microcks ingress + Preview URLs):

```bash
LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Ingress LB: $LB_IP"
```

### 3.3 OpenTelemetry Operator + Jaeger

```bash
helm install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator-system --create-namespace \
  --set admissionWebhooks.certManager.enabled=true \
  --set manager.collectorImage.repository=otel/opentelemetry-collector-contrib \
  --wait

kubectl -n opentelemetry-operator-system rollout status deployment/opentelemetry-operator --timeout=180s

kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-preview/main/jaeger.yaml
kubectl -n observability rollout status deployment/jaeger --timeout=180s

kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-preview/main/otel.yaml
```

The `otel-collector` deployment takes a few seconds to appear (the operator reconciles
the `OpenTelemetryCollector` CR). Wait for it:

```bash
until kubectl get deploy -n observability otel-collector >/dev/null 2>&1; do sleep 5; done
kubectl -n observability rollout status deployment/otel-collector --timeout=120s
```

### 3.4 Preview Operator

The Helm chart lives in a separate repo (`ihsenalaya/preview-operator`). Clone it
once at a sibling path.

```bash
cd /tmp
git clone --depth 1 https://github.com/ihsenalaya/preview-operator.git
cd preview-operator
```

Apply CRDs separately (Helm does not update CRDs on upgrade):

```bash
kubectl apply -f charts/preview-operator/crds/platform.company.io_previews.yaml
kubectl apply -f charts/preview-operator/crds/platform.company.io_reconcileevents.yaml
kubectl apply -f charts/preview-operator/crds/platform.company.io_testplans.yaml
kubectl apply -f charts/preview-operator/crds/platform.company.io_testruns.yaml
```

Install the operator:

```bash
helm install preview-operator ./charts/preview-operator \
  --namespace preview-operator-system --create-namespace \
  --set image.repository=ghcr.io/ihsenalaya/preview-operator \
  --set image.tag=1.0.43 \
  --set previewDomain=preview.ihsenalaya.xyz \
  --set "ai.apiURL=${AOAI_ENDPOINT}openai/deployments/gpt-4o-mini"
# AOAI_ENDPOINT only used if you set up Azure OpenAI (Step 3.6). Otherwise omit.

kubectl -n preview-operator-system rollout status deployment/preview-operator --timeout=180s
```

### 3.5 Microcks

```bash
helm install microcks microcks/microcks \
  --namespace microcks --create-namespace \
  --set "microcks.url=microcks.${LB_IP}.nip.io" \
  --set "microcks.ingressClassName=nginx" \
  --set "microcks.generateCert=false" \
  --set "keycloak.url=keycloak.${LB_IP}.nip.io" \
  --set "keycloak.privateUrl=http://microcks-keycloak.microcks.svc.cluster.local:8080" \
  --set "keycloak.ingressClassName=nginx" \
  --set "keycloak.generateCert=false"

kubectl -n microcks rollout status deployment/microcks --timeout=300s
```

### 3.6 Azure OpenAI (optional, required for AI enrichment in RQ4)

```bash
az cognitiveservices account create \
  --name preview-openai-idp \
  --resource-group "$RG" \
  --kind OpenAI \
  --sku S0 \
  --location "$LOCATION" \
  --custom-domain preview-openai-idp

az cognitiveservices account deployment create \
  --name preview-openai-idp \
  --resource-group "$RG" \
  --deployment-name gpt-4o-mini \
  --model-name gpt-4o-mini \
  --model-version 2024-07-18 \
  --model-format OpenAI \
  --sku-name GlobalStandard \
  --sku-capacity 30

AOAI_ENDPOINT=$(az cognitiveservices account show \
  --name preview-openai-idp --resource-group "$RG" \
  --query "properties.endpoint" -o tsv | tr -d '\r\n')
AOAI_KEY=$(az cognitiveservices account keys list \
  --name preview-openai-idp --resource-group "$RG" \
  --query "key1" -o tsv | tr -d '\r\n')
```

### 3.7 kagent (optional, AI failure analysis)

```bash
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent-system --create-namespace

helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent-system

kubectl -n kagent-system rollout status deployment/kagent-controller --timeout=180s
```

Configure model + secrets (skip if no Azure OpenAI):

```bash
GH_TOKEN=$(cat ~/.config/gh/hosts.yml | grep oauth_token | awk '{print $2}' | tr -d '\r\n')

kubectl create secret generic kagent-openai -n kagent-system \
  --from-literal=OPENAI_API_KEY="$AOAI_KEY"

kubectl create secret docker-registry ghcr-pull-secret -n kagent-system \
  --docker-server=ghcr.io \
  --docker-username=ihsenalaya \
  --docker-password="$GH_TOKEN"

# Patch the default model config to use Azure OpenAI
kubectl patch modelconfig default-model-config -n kagent-system --type=merge -p "{
  \"spec\": {
    \"provider\": \"AzureOpenAI\",
    \"model\": \"gpt-4o-mini\",
    \"apiKeySecret\": \"kagent-openai\",
    \"apiKeySecretKey\": \"OPENAI_API_KEY\",
    \"azureOpenAI\": {
      \"azureEndpoint\": \"${AOAI_ENDPOINT%/}\",
      \"azureDeployment\": \"gpt-4o-mini\",
      \"apiVersion\": \"2024-10-21\"
    }
  }
}"

# Deploy RBAC + MCP server + the troubleshooter agent
cd /tmp
git clone --depth 1 https://github.com/ihsenalaya/idp-preview.git
cd idp-preview
kubectl apply -f k8s/kagent/rbac-readonly.yaml
kubectl apply -f k8s/kagent/jaeger-mcp-server.yaml
kubectl rollout status deployment/jaeger-mcp-server -n kagent-system --timeout=180s
kubectl apply -f k8s/kagent/preview-troubleshooter-agent.yaml
```

### 3.8 Operator secrets

```bash
GH_TOKEN=$(cat ~/.config/gh/hosts.yml | grep oauth_token | awk '{print $2}' | tr -d '\r\n')

kubectl create secret generic ai-api-key -n preview-operator-system \
  --from-literal=api-key="$AOAI_KEY"

kubectl create secret generic preview-github-token -n preview-operator-system \
  --from-literal=token="$GH_TOKEN"

kubectl create secret generic azure-openai-credentials -n preview-operator-system \
  --from-literal=api-key="$AOAI_KEY"
```

### 3.9 Self-hosted GitHub Actions runner (optional, only for live PR previews)

```bash
kubectl create namespace github-runner --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic runner-token -n github-runner \
  --from-literal=token="$GH_TOKEN"
kubectl apply -f /tmp/idp-preview/runner.yaml
kubectl -n github-runner rollout status deployment/github-runner --timeout=180s

gh secret set PREVIEW_GITHUB_TOKEN --repo ihsenalaya/idp-preview --body "$GH_TOKEN"
```

---

## 4. GHCR private images — the pull-secret pull-race

**Symptom**: every preview-pr-\<N\> namespace is created by the operator, then the operator
immediately creates the `postgres-migrate` Job inside it. If you only push an
imagePullSecret manually, the Job's pod is admitted by the K8s API before the
secret is applied, so the pod has empty `spec.imagePullSecrets`. Kubernetes does
not re-evaluate that field after pod admission, so the pull fails with 401 anonymous.

**Solution**: two watchers running in `kube-system`:

1. **`ghcr-propagator`** — watches namespace creation. For each new `preview-pr-*` ns, copies the docker-registry secret and patches the ns's `default` ServiceAccount to use it as imagePullSecret.
2. **`ghcr-killloop`** — every 5 s, deletes any pod stuck in `ImagePullBackOff` / `ErrImagePull` in any `preview-pr-*` namespace. The Job recreates it, and the new pod inherits the now-patched ServiceAccount.

### Apply the watchers

```bash
GH_TOKEN=$(cat ~/.config/gh/hosts.yml | grep oauth_token | awk '{print $2}' | tr -d '\r\n')

# Template secret in kube-system (the propagator copies it into each ns)
kubectl create secret docker-registry ghcr-pull-secret-template -n kube-system \
  --docker-server=ghcr.io \
  --docker-username=ihsenalaya \
  --docker-password="$GH_TOKEN"

cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata: {name: ghcr-propagator, namespace: kube-system}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: ghcr-propagator}
rules:
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get","list","watch"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get","create","patch","update"]
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get","patch","update"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get","list","delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: ghcr-propagator}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: ghcr-propagator}
subjects: [{kind: ServiceAccount, name: ghcr-propagator, namespace: kube-system}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: ghcr-propagator, namespace: kube-system}
spec:
  replicas: 1
  selector: {matchLabels: {app: ghcr-propagator}}
  template:
    metadata: {labels: {app: ghcr-propagator}}
    spec:
      serviceAccountName: ghcr-propagator
      containers:
        - name: propagator
          image: alpine/k8s:1.30.5
          command: ["/bin/sh","-c"]
          args:
            - |
              kubectl get ns -w -o jsonpath='{.metadata.name}{"\n"}' --watch-only | while read ns; do
                if [[ "$ns" == preview-pr-* ]]; then
                  echo "[$(date -u +%T)] new ns: $ns"
                  kubectl get secret ghcr-pull-secret-template -n kube-system -o yaml \
                    | sed "s/namespace: kube-system/namespace: $ns/" \
                    | sed "s/name: ghcr-pull-secret-template/name: ghcr-pull-secret/" \
                    | grep -v "uid:\\|resourceVersion:\\|creationTimestamp:" \
                    | kubectl apply -f - || true
                  kubectl patch serviceaccount default -n "$ns" \
                    -p '{"imagePullSecrets":[{"name":"ghcr-pull-secret"}]}' || true
                fi
              done
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: ghcr-killloop, namespace: kube-system}
spec:
  replicas: 1
  selector: {matchLabels: {app: ghcr-killloop}}
  template:
    metadata: {labels: {app: ghcr-killloop}}
    spec:
      serviceAccountName: ghcr-propagator
      containers:
        - name: killer
          image: alpine/k8s:1.30.5
          command: ["/bin/sh","-c"]
          args:
            - |
              while true; do
                for ns in $(kubectl get ns -o name | grep "preview-pr-" | sed 's|namespace/||'); do
                  bad=$(kubectl get pods -n "$ns" -o json 2>/dev/null \
                    | jq -r '.items[] | select(.status.containerStatuses[]?.state.waiting.reason // "" | test("ImagePullBackOff|ErrImagePull")) | .metadata.name' 2>/dev/null)
                  for p in $bad; do
                    kubectl delete pod "$p" -n "$ns" --grace-period=0 --force 2>&1 | head -1
                  done
                done
                sleep 5
              done
EOF

kubectl -n kube-system rollout status deployment/ghcr-propagator --timeout=120s
kubectl -n kube-system rollout status deployment/ghcr-killloop --timeout=120s
```

> **Why not just make the GHCR packages public?** GitHub's API does not expose
> visibility change for personal packages — only via the web UI. The watchers
> approach keeps packages private and works automatically for new namespaces.

---

## 5. Adapter images — build and push

The harness references images with `-fix` / `:cached` tags that exist only in the
local Kind cluster. On AKS the cluster pulls from GHCR, so these tags must be
published.

### 5.1 Login to GHCR

```bash
GH_TOKEN=$(cat ~/.config/gh/hosts.yml | grep oauth_token | awk '{print $2}' | tr -d '\r\n')
echo "$GH_TOKEN" | docker login ghcr.io -u ihsenalaya --password-stdin
```

### 5.2 Build and push

From the experimentation repo root:

```bash
# Probe sidecar — :cached is just a retag of :latest (used to pin pull policy)
docker tag ghcr.io/ihsenalaya/harness-probe:latest ghcr.io/ihsenalaya/harness-probe:cached
docker push ghcr.io/ihsenalaya/harness-probe:cached

# S2 Listmonk adapter
docker build -t ghcr.io/ihsenalaya/s2-listmonk-adapter:v2.5.1-fix \
  subjects/s2-listmonk/harness-adapter/
docker push ghcr.io/ihsenalaya/s2-listmonk-adapter:v2.5.1-fix

# S3 Healthchecks adapter
docker build -t ghcr.io/ihsenalaya/s3-healthchecks-adapter:v3.6-fix \
  subjects/s3-healthchecks/harness-adapter/
docker push ghcr.io/ihsenalaya/s3-healthchecks-adapter:v3.6-fix

# S5 PetClinic adapter (see §7 for the four bugs that this image fixes)
docker build -t ghcr.io/ihsenalaya/s5-petclinic-adapter:v3.4.0-fix3 \
  subjects/s5-petclinic/harness-adapter/
docker push ghcr.io/ihsenalaya/s5-petclinic-adapter:v3.4.0-fix3

# S4 Umami and probe are already on GHCR with the expected tags; no rebuild needed.
```

### 5.3 Verify config.yaml tags match

```yaml
subjects:
  probe_image: ghcr.io/ihsenalaya/harness-probe:cached
  images:
    s1-flask-catalog: ghcr.io/ihsenalaya/idp-preview:exp-20260514-e2efix-2089
    s2-listmonk:      ghcr.io/ihsenalaya/s2-listmonk-adapter:v2.5.1-fix
    s3-healthchecks:  ghcr.io/ihsenalaya/s3-healthchecks-adapter:v3.6-fix
    s4-umami:         ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1
    s5-petclinic:     ghcr.io/ihsenalaya/s5-petclinic-adapter:v3.4.0-fix3
```

If you push a new digest under the same tag, AKS may keep the cached old digest
(default `imagePullPolicy: IfNotPresent`). Bump the tag (`-fix2`, `-fix3`, …) to
force a fresh pull.

---

## 6. Running experiments

### 6.1 Sequential (one Python process per experiment)

```bash
KUBECONFIG=$HOME/.kube/config PYTHONPATH=$(pwd) bash run-all-experiments.sh
```

This runs RQ1 → RQ2 → RQ3 → RQ4 → RQ5 in order, iterating over `subjects.enabled`
inside each experiment. Expected wall clock on AKS: ~5 h end-to-end.

### 6.2 Per-subject parallel (recommended)

`_run_one_subject.py` monkeypatches `cfg.subjects.enabled` to a single subject so
multiple instances can run in parallel without colliding on `pr_number` ranges or
config state.

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p logs

for sub in s2-listmonk s3-healthchecks s4-umami s5-petclinic; do
  for exp in flakiness performance; do
    nohup env SUBJECT=$sub EXPERIMENT=$exp \
      KUBECONFIG=$HOME/.kube/config PYTHONPATH=$(pwd) \
      python3 -u _run_one_subject.py \
      > "logs/${exp}-${sub}-${TS}.log" 2>&1 &
  done
done
```

Eight parallel processes producing eight CSV streams. Idempotence is **not**
parallelized — it kills the operator pod, which breaks any concurrent Preview
creation. Run it alone after the others finish:

```bash
nohup env KUBECONFIG=$HOME/.kube/config PYTHONPATH=$(pwd) \
  python3 -u exp_idempotence/run.py \
  > "logs/idempotence-$(date -u +%Y%m%dT%H%M%SZ).log" 2>&1 &
```

Bug detection has its own wrapper because RQ4 should be scoped to a smaller set of
subjects (only S1 has mutation-relevant code):

```bash
nohup env KUBECONFIG=$HOME/.kube/config PYTHONPATH=$(pwd) \
  python3 -u _run_bug_detection_s1s2.py \
  > "logs/bug_detection-s1s2-$(date -u +%Y%m%dT%H%M%SZ).log" 2>&1 &
```

### 6.3 Verify a run

```bash
# Processes
pgrep -fa "python3 -u" | grep -v bash

# Previews
kubectl get preview

# Cluster usage
kubectl top nodes

# CSV growth
find results -name "*$(date -u +%Y%m%d)*.csv" -exec wc -l {} \;
```

---

## 7. S5 PetClinic — four bugs, four fixes

The S5 adapter image required four distinct fixes before the pipeline could run
end-to-end. Documented in detail so the same root causes are not rediscovered.

### Bug 1 — wrapper.py never executes

The `springcommunity/spring-petclinic-rest:3.4.0` base image is built with Jib,
which sets `ENTRYPOINT ["java", "-cp", "@/app/jib-classpath-file", "...PetClinicApplication"]`.
A Dockerfile that only sets `CMD ["python3", "/wrapper.py"]` passes `python3 /wrapper.py`
as **args** to the Jib ENTRYPOINT, so Java starts directly and wrapper.py is never
invoked.

**Fix**: override ENTRYPOINT explicitly.

```dockerfile
ENTRYPOINT ["python3"]
CMD ["/wrapper.py"]
```

### Bug 2 — `python: not found` in test jobs

`smoke-tests` and `regression-tests` jobs invoke `python` (no `3`). The Debian base
of the PetClinic image only ships `python3` after `apt install python3 python3-pip`.

**Fix**: add a symlink in the Dockerfile.

```dockerfile
RUN ln -sf /usr/bin/python3 /usr/local/bin/python
```

### Bug 3 — `/api/pets` returns 404 HTML

The baked `application.properties` has `server.servlet.context-path=/petclinic/`,
so Spring Boot answers on `/petclinic/api/pets`. The harness tests call `/api/pets`
directly, getting a Spring error page that fails JSON decoding.

**Fix**: override via env in `wrapper.py` before launching Spring Boot.

```python
env["SERVER_SERVLET_CONTEXT_PATH"] = "/"
```

### Bug 4 — `relation "pets" does not exist` on every endpoint

The migration looked successful (`PASS migration petclinic flyway: OK`) but the
postgres database only contained the `run_log` table (created by the probe sidecar,
not by Spring Boot). PetClinic does **not** use Flyway — it uses Spring Boot's
`spring.sql.init` mechanism gated on the active profile.

The image ships `application-postgres.properties`, which maps to profile name
**`postgres`**. The harness was setting `SPRING_PROFILES_ACTIVE=postgresql`
(an unknown profile), so Spring fell back to `application.properties` whose default
is `database=hsqldb` (in-memory). Result: PetClinic boots an HSQL session, never
touches Postgres, and the seed SQL never runs.

**Fix**: in both `subjects/s5-petclinic/meta.yaml` (migration command) and
`subjects/s5-petclinic/harness-adapter/wrapper.py`, change the profile name:

```python
env["SPRING_PROFILES_ACTIVE"] = "postgres,spring-data-jpa"   # was "postgresql,..."
```

After all four fixes, the image rebuilt as `v3.4.0-fix3` passes the validation
suite: `/healthz 200`, `/api/pets 200 (13 items)`, `/api/vets 200 (6 items)`,
`/api/owners 200 (10 items)` — the seed counts match `meta.yaml` exactly.

---

## 8. Other gotchas

### Idempotence and parallel experiments

`exp_idempotence` deliberately kills the operator pod at specific pipeline steps
to measure convergence time. While the operator is restarting, the validating
admission webhook is unreachable, so **any other process trying to create a Preview
CR fails with `kubectl apply -f -` non-zero exit**. The whole experiment script
crashes on the first such failure (no retry in `factory.create`).

**Don't run idempotence in parallel with other experiments.** Run it last, alone.

### Cluster CPU requests cap

The `medium` resource tier requests `200m` CPU per container × ~5 containers per
Preview. With 10 concurrent Previews you can saturate the per-node CPU **requests**
budget even when actual CPU usage is around 30 %. Symptom: new Previews stuck in
`Provisioning` because the operator's pod ends up `Pending` with
`0/2 nodes available, 2 Insufficient cpu`.

Mitigation: either scale the node pool (`az aks scale --resource-group $RG --name $CLUSTER --node-count 3`)
or cap parallelism at ~8 concurrent Previews on a 2× D4s_v3 cluster.

### kubeconfig path on WSL

Always merge into `$HOME/.kube/config` via the pipeline in §1 — never pass
`--file ~/.kube/config` directly to `az`. The `az` CLI writes a Windows-style
absolute path that `kubectl` cannot resolve from the Linux side.

### Resource Group locks

If `az aks delete` fails with `ScopeLocked`, an RG-level lock exists. Check via:

```bash
az rest --method get \
  --uri "https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG/providers/Microsoft.Authorization/locks?api-version=2016-09-01"
```

`az lock list` may return empty even when a lock exists at a higher scope; the
REST endpoint is authoritative.

### VM custom-data ignored on WSL

`az vm create --custom-data <file>` sometimes results in an empty cloud-config on
the VM (Azure WALinuxAgent fails to inject through some WSL paths). If the bootstrap
runs but tools are not installed, SCP a setup script and run it via SSH instead of
relying on cloud-init.

---

## 9. Teardown

```bash
az aks delete --resource-group "$RG" --name "$CLUSTER" --yes
az cognitiveservices account delete --resource-group "$RG" --name preview-openai-idp
az group delete --name "$RG" --yes  # only if no other resources in the RG
```
