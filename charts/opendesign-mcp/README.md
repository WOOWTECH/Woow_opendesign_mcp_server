# opendesign-mcp

Helm chart for the Open Design MCP server and its admin console — the
application in this repository. One release per instance.

The pod runs `entrypoint.sh`, which starts two processes side by side and exits
as soon as either one dies:

| process      | port | what it serves                                                        |
| ------------ | ---- | --------------------------------------------------------------------- |
| supergateway | 8000 | FastMCP's 15 stdio tools bridged to StreamableHttp, `/healthz`. **No authentication of its own.** |
| uvicorn      | 8080 | FastAPI admin console (JWT), the `/private_{token}/mcp` reverse proxy, `/healthz` |

`/data` is a PVC: `config.json` holds the admin password, the current MCP token
and the rotation history.

*繁體中文版：[README_zh-TW.md](README_zh-TW.md)*

## Install

The chart does **not** create the Secret by default — it only references it, so
a `helm upgrade` can never write an empty value over a rotated `JWT_SECRET`.

```bash
# 1. Credentials, out of band. Copy the example OUTSIDE the repo and fill it in.
cp examples/secrets.example.yaml /secure/path/od-mcp-secrets.yaml
$EDITOR /secure/path/od-mcp-secrets.yaml     # JWT_SECRET: openssl rand -hex 32
kubectl -n open-design apply -f /secure/path/od-mcp-secrets.yaml

# 2a. From a clone
git clone https://github.com/WOOWTECH/Woow_opendesign_mcp_server
cd Woow_opendesign_mcp_server
helm -n open-design upgrade --install od-mcp ./charts/opendesign-mcp \
  -f deploy/local/od-mcp.yaml

# 2b. From a GitHub tarball, no clone. The chart is not published to a
#     registry, so unpack the repo and point helm at the chart directory.
curl -sSL https://github.com/WOOWTECH/Woow_opendesign_mcp_server/archive/refs/heads/main.tar.gz | tar -xz
helm -n open-design upgrade --install od-mcp \
  ./Woow_opendesign_mcp_server-main/charts/opendesign-mcp \
  -f ./Woow_opendesign_mcp_server-main/deploy/local/od-mcp.yaml
```

Let the chart render the Secret instead (fresh installs, throwaway test
namespaces) with `--set secrets.create=true,secrets.jwtSecret=...,secrets.adminPassword=...`.
Both are enforced by `required()`.

### The image

`image.mode` decides how the application gets into the pod:

* **`prebuilt`** (default, and what runs live) — `localhost/od-mcp:latest`
  with `imagePullPolicy: Never`, built on the node itself
  (`podman build -t od-mcp:latest .` in this repo). Nothing is published to a
  registry, so the pod only schedules on the node that has the image; that is
  what `nodeSelector` in `deploy/local/od-mcp.yaml` pins.
* **`source`** — clone this repo and install the dependencies on start, the
  runtime model the other WOOWTECH MCP charts use. Needs no registry and no
  local build, so it is what the chart is tested with on woow-k3s. It uses a
  python+node image because `entrypoint.sh` needs both.

Phase 1 does not change how the live pod is built; `source` is an addition, off
by default.

## Key values

| value | default | notes |
| ----- | ------- | ----- |
| `namespace.create` / `namespace.name` | `true` / `open-design` | a Namespace equal to `--namespace` is never rendered, so `helm uninstall` cannot delete the release's own namespace |
| `keepOnUninstall` | `true` | `helm.sh/resource-policy: keep` on the Namespace, the PVC and the chart-created Secret |
| `fullnameOverride` | `od-mcp` | names **and** the selector/pod-template label. Changing it re-creates the ReplicaSet |
| `image.mode` | `prebuilt` | `prebuilt` \| `source` |
| `image.repository` / `.tag` / `.pullPolicy` | `localhost/od-mcp` / `latest` / `Never` | prebuilt mode only |
| `source.gitRepo` / `.gitRef` / `.images.runtime` | this repo / default branch / `nikolaik/python-nodejs:python3.12-nodejs22-slim` | source mode only |
| `secrets.create` | `false` | `true` renders `od-mcp-secrets` from `secrets.jwtSecret` + `secrets.adminPassword` (both `required()`) |
| `secrets.existingSecret` | `""` | `""` = `<fullname>-secrets` |
| `persistence.storageClassName` | `local-path` | local cluster. woow-k3s: `longhorn-delete` (tests) or `longhorn` |
| `od.apiBase` | `http://open-design-svc:7457` | the Open Design daemon the 15 tools call |
| `probes.*` | live values | `startup` 12×5s, `readiness` 3×10s, `liveness` 3×30s. Source mode needs a much longer startup budget |
| `networkPolicy.allowFromAllNamespaces` | `true` | reproduces live. See the caveat below |
| `networkPolicy.allowFromCidrs` | `[]` | extra `ipBlock` rule |
| `hardening.*` | `{}` | opt-in, see follow-ups |
| `tests.enabled` | `true` | read-only `helm test` pod |

### NetworkPolicy caveat

The live policy allows ingress to 8080 and 8000 `from: [{namespaceSelector: {}},
{podSelector: {}}]` — that is, from everywhere, including the unauthenticated
supergateway port. The chart keeps it because phase 1 must not change live
behaviour.

On woow-k3s (k3s 1.34) those selectors are **not** matched for traffic arriving
through the ClusterIP Service: every connection is rejected until an `ipBlock`
rule is added. If you install this chart on woow-k3s with the policy enabled,
set `networkPolicy.allowFromCidrs` (`["0.0.0.0/0"]` reproduces the live intent,
a pod CIDR such as `["10.42.0.0/16"]` is tighter).

## Verify

```bash
kubectl -n open-design rollout status deploy/od-mcp
helm  -n open-design test od-mcp --logs        # admin + supergateway /healthz
kubectl -n open-design port-forward svc/od-mcp-svc 8080:8080 &
curl -s localhost:8080/healthz                 # {"status":"ok"}
```

`helm test` is read-only: two unauthenticated GETs, no token use, no writes.
The pod is kept until the next run (`hook-delete-policy: before-hook-creation`)
so `helm test --logs` can always read it.

Drift against a cluster:

```bash
CONTEXT=default RELEASE=od-mcp NAMESPACE=open-design scripts/check-drift.sh
```

## Uninstall keeps the data

```bash
helm -n open-design uninstall od-mcp
```

With `keepOnUninstall: true` the Deployment, Service and NetworkPolicy go and
the PVC `od-mcp-data`, the Secret `od-mcp-secrets` and the Namespace stay, so
`/data/config.json` — the admin password, the MCP token and its history —
survives. Verified on woow-k3s: after `helm uninstall` the PVC was still
`Bound`, the Secret still had both keys, and reinstalling came back to the same
`config.json`. To actually drop the data, delete the PVC by hand.

## Taking over the running instance

The live instance (local cluster, `--context default`, namespace
`open-design`) was created with `kubectl apply` from manifests that lived in the
now-archived `Woow_opendesign_docker_compose_all`. Rendering this chart with
`deploy/local/od-mcp.yaml` reproduces its Deployment and Service field for
field, so adopting them restarts nothing:

```bash
helm --kube-context default -n open-design upgrade --install od-mcp \
  ./charts/opendesign-mcp -f deploy/local/od-mcp.yaml --take-ownership
```

Two things in `deploy/local/od-mcp.yaml` exist only to keep the pod template
hash identical and must not be dropped: the `nodeSelector` pinning the node
that holds the locally built image, and the `kubectl.kubernetes.io/restartedAt`
pod annotation left by the last manual rollout restart. The PVC gains the
`helm.sh/resource-policy: keep` annotation (an annotation only — it does not
restart anything).

The takeover itself is **not** part of phase 1; the command above is written
down so it can be run deliberately later.

## Known issues this chart does not fix (follow-ups)

Phase 1 only reshapes the deployment. Everything below changes runtime
behaviour and is therefore off by default:

1. **Rotate `JWT_SECRET`.** The value the live Secret holds was committed in
   plain text in the public, archived `Woow_opendesign_docker_compose_all`
   (`k8s-manifests/10-mcp-deployment.yaml`). Anyone with it can mint an admin
   JWT. This chart never commits it — `secrets.create` is `false` and
   `examples/secrets.example.yaml` holds placeholders only — but the live value
   is unchanged and must be rotated.
2. **The admin password is `admin`.** `ADMIN_PASSWORD` is injected but never
   read: the login password lives in `/data/config.json` and is seeded as
   `admin` on the first boot. Change it in the console's Settings page.
3. **Admin API → RCE.** `PUT /api/settings/mcp_server` accepts any
   `command`/`args` and `POST /api/settings/mcp/restart` runs them as root.
   Combined with 1 and 2 this is unauthenticated remote code execution.
   `hardening.podSecurityContext` / `hardening.containerSecurityContext` are
   there to run the pod unprivileged; both change the pod template, so enabling
   them rolls the pod.
4. **Port 8000 is unauthenticated.** supergateway has no auth of its own and
   the Service publishes it, so the `/private_{token}` check on 8080 can be
   bypassed — including `delete_project`. Tightening `networkPolicy` (set
   `allowFromAllNamespaces: false`) or dropping the `mcp` port from the Service
   is the fix.
5. **Probes only watch 8080.** supergateway's own `/healthz` on 8000 is never
   probed, so it can hang without the container being restarted.
6. **`localhost/od-mcp:latest` is not reproducible.** No CI, no registry, no
   tag — the running image cannot be traced back to a commit. `image.mode:
   source` is a workaround, publishing the image is the fix.
