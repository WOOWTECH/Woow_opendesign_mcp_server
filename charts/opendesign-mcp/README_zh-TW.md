# opendesign-mcp

Open Design MCP server 與管理介面（也就是本 repo 的程式）的 Helm chart。
一個 instance 一個 release。

Pod 跑的是 `entrypoint.sh`，它同時啟動兩個程序，任一個結束整個容器就退出：

| 程序          | 埠   | 提供什麼                                                            |
| ------------- | ---- | ------------------------------------------------------------------- |
| supergateway  | 8000 | 把 FastMCP 的 15 個 stdio tools 轉成 StreamableHttp，另有 `/healthz`。**它自己沒有任何驗證。** |
| uvicorn       | 8080 | FastAPI 管理介面（JWT）、`/private_{token}/mcp` 反向代理、`/healthz` |

`/data` 是 PVC：`config.json` 存放管理員密碼、目前的 MCP token 和輪替歷史。

*English: [README.md](README.md)*

## 安裝

預設 chart **不會**建立 Secret，只會引用它 —— 這樣 `helm upgrade` 就不可能把
已經輪替過的 `JWT_SECRET` 寫成空值。

```bash
# 1. 憑證另外處理。把範例複製到 repo 外面再填寫。
cp examples/secrets.example.yaml /secure/path/od-mcp-secrets.yaml
$EDITOR /secure/path/od-mcp-secrets.yaml     # JWT_SECRET：openssl rand -hex 32
kubectl -n open-design apply -f /secure/path/od-mcp-secrets.yaml

# 2a. 用 clone
git clone https://github.com/WOOWTECH/Woow_opendesign_mcp_server
cd Woow_opendesign_mcp_server
helm -n open-design upgrade --install od-mcp ./charts/opendesign-mcp \
  -f deploy/local/od-mcp.yaml

# 2b. 用 GitHub tarball，不 clone。chart 沒有發布到 registry，
#     所以先解開整個 repo 再指向 chart 目錄。
curl -sSL https://github.com/WOOWTECH/Woow_opendesign_mcp_server/archive/refs/heads/main.tar.gz | tar -xz
helm -n open-design upgrade --install od-mcp \
  ./Woow_opendesign_mcp_server-main/charts/opendesign-mcp \
  -f ./Woow_opendesign_mcp_server-main/deploy/local/od-mcp.yaml
```

想讓 chart 自己產生 Secret（全新安裝、拋棄式測試 namespace）就加
`--set secrets.create=true,secrets.jwtSecret=...,secrets.adminPassword=...`，
兩個值都有 `required()` 把關。

### Image

`image.mode` 決定程式怎麼進到 pod：

* **`prebuilt`**（預設，也是線上跑的方式）—— `localhost/od-mcp:latest`，
  `imagePullPolicy: Never`，image 直接在節點上建
  （在本 repo 執行 `podman build -t od-mcp:latest .`）。沒有推到任何 registry，
  所以 pod 只能排到有這個 image 的節點上，`deploy/local/od-mcp.yaml` 的
  `nodeSelector` 就是釘這個。
* **`source`** —— 啟動時 clone 本 repo 並安裝相依套件，和其他 WOOWTECH MCP
  chart 相同的執行模型。不需要 registry 也不需要本機 build，所以 chart 在
  woow-k3s 上就是用這個模式測的。因為 `entrypoint.sh` 同時需要 python 和
  node，所以用的是 python+node 的 image。

phase 1 不改線上 pod 的建置方式；`source` 是新增的選項，預設關閉。

## 主要 values

| value | 預設 | 說明 |
| ----- | ---- | ---- |
| `namespace.create` / `namespace.name` | `true` / `open-design` | 與 `--namespace` 相同的 Namespace 永遠不會被渲染，`helm uninstall` 就不可能刪掉 release 自己所在的 namespace |
| `keepOnUninstall` | `true` | 在 Namespace、PVC 和 chart 建立的 Secret 上加 `helm.sh/resource-policy: keep` |
| `fullnameOverride` | `od-mcp` | 同時決定資源名稱**和** selector／pod template label。改它會重建 ReplicaSet |
| `image.mode` | `prebuilt` | `prebuilt` \| `source` |
| `image.repository` / `.tag` / `.pullPolicy` | `localhost/od-mcp` / `latest` / `Never` | 只在 prebuilt 模式使用 |
| `source.gitRepo` / `.gitRef` / `.images.runtime` | 本 repo／預設分支／`nikolaik/python-nodejs:python3.12-nodejs22-slim` | 只在 source 模式使用 |
| `secrets.create` | `false` | `true` 時用 `secrets.jwtSecret` + `secrets.adminPassword` 產生 `od-mcp-secrets`（兩者皆 `required()`） |
| `secrets.existingSecret` | `""` | `""` 表示 `<fullname>-secrets` |
| `persistence.storageClassName` | `local-path` | local cluster 用。woow-k3s 用 `longhorn-delete`（測試）或 `longhorn` |
| `od.apiBase` | `http://open-design-svc:7457` | 15 個 tools 要打的 Open Design daemon |
| `probes.*` | 與線上相同 | `startup` 12×5s、`readiness` 3×10s、`liveness` 3×30s。source 模式需要長很多的啟動時間 |
| `networkPolicy.allowFromAllNamespaces` | `true` | 重現線上設定，注意下面的陷阱 |
| `networkPolicy.allowFromCidrs` | `[]` | 額外的 `ipBlock` 規則 |
| `hardening.*` | `{}` | 需自行開啟，見「後續待辦」 |
| `tests.enabled` | `true` | 唯讀的 `helm test` pod |

### NetworkPolicy 的陷阱

線上的 policy 對 8080 和 8000 開放
`from: [{namespaceSelector: {}}, {podSelector: {}}]`，等於對所有來源開放，
包含沒有驗證的 supergateway 埠。chart 保留這個設定，因為 phase 1 不能改變
線上行為。

在 woow-k3s（k3s 1.34）上，這些 selector 對「經由 ClusterIP Service 進來的
流量」**不會**命中：在加上 `ipBlock` 規則之前，每一條連線都會被拒絕。若要在
woow-k3s 上啟用這個 policy，請設定 `networkPolicy.allowFromCidrs`
（`["0.0.0.0/0"]` 等同線上語意，`["10.42.0.0/16"]` 這種 pod CIDR 更緊）。

## 驗證

```bash
kubectl -n open-design rollout status deploy/od-mcp
helm  -n open-design test od-mcp --logs        # admin 與 supergateway 的 /healthz
kubectl -n open-design port-forward svc/od-mcp-svc 8080:8080 &
curl -s localhost:8080/healthz                 # {"status":"ok"}
```

`helm test` 是唯讀的：兩個不需驗證的 GET，不用 token、不寫入任何東西。
pod 會留到下一次執行（`hook-delete-policy: before-hook-creation`），
所以 `helm test --logs` 隨時讀得到。

和叢集比對漂移：

```bash
CONTEXT=default RELEASE=od-mcp NAMESPACE=open-design scripts/check-drift.sh
```

## 解除安裝不會刪資料

```bash
helm -n open-design uninstall od-mcp
```

`keepOnUninstall: true` 時，Deployment、Service、NetworkPolicy 會被移除，而
PVC `od-mcp-data`、Secret `od-mcp-secrets` 和 Namespace 會留下，所以
`/data/config.json`（管理員密碼、MCP token 與歷史）不會消失。已在 woow-k3s
實測：`helm uninstall` 之後 PVC 仍是 `Bound`、Secret 兩把 key 都在，重新安裝
回到同一份 `config.json`。真的要刪資料請手動刪 PVC。

## 接管線上那一份

線上那份（local cluster、`--context default`、namespace `open-design`）當初是
用 `kubectl apply` 從已封存的 `Woow_opendesign_docker_compose_all` 的 manifest
建的。用 `deploy/local/od-mcp.yaml` 渲染本 chart 會逐欄位重現它的 Deployment
與 Service，所以接管不會重啟任何東西：

```bash
helm --kube-context default -n open-design upgrade --install od-mcp \
  ./charts/opendesign-mcp -f deploy/local/od-mcp.yaml --take-ownership
```

`deploy/local/od-mcp.yaml` 裡有兩項純粹是為了讓 pod template hash 保持一致，
不能拿掉：釘住那台有本機 image 的節點的 `nodeSelector`，以及上一次手動
rollout restart 留下的 `kubectl.kubernetes.io/restartedAt` pod annotation。
PVC 會多一個 `helm.sh/resource-policy: keep` annotation（只是 annotation，
不會造成重啟）。

接管本身**不屬於** phase 1；上面的指令只是先寫下來，之後再刻意執行。

## 本 chart 沒有處理的問題（後續待辦）

phase 1 只重整部署方式。以下每一項都會改變執行時行為，所以預設都關閉：

1. **輪替 `JWT_SECRET`。** 線上 Secret 裡的值，曾以明文 commit 在公開且已封存
   的 `Woow_opendesign_docker_compose_all`（`k8s-manifests/10-mcp-deployment.yaml`）。
   拿到它的人就能自行簽出管理員 JWT。本 chart 完全不會 commit 它 ——
   `secrets.create` 預設 `false`，`examples/secrets.example.yaml` 只有 placeholder
   —— 但線上那個值還沒換，必須輪替。
2. **管理員密碼是 `admin`。** `ADMIN_PASSWORD` 有注入但程式根本不讀：登入密碼
   存在 `/data/config.json`，第一次啟動時寫入 `admin`。請到管理介面的 Settings
   頁改掉。
3. **管理 API 等於 RCE。** `PUT /api/settings/mcp_server` 可以塞任意
   `command`/`args`，`POST /api/settings/mcp/restart` 就會以 root 執行。配上第
   1、2 點，等於未授權遠端執行。`hardening.podSecurityContext` 和
   `hardening.containerSecurityContext` 就是給你用來降權的；兩者都會改變 pod
   template，開啟時會滾動重啟。
4. **8000 埠沒有驗證。** supergateway 自己沒有驗證，Service 又把它開出去，
   所以可以繞過 8080 的 `/private_{token}` 檢查，包含 `delete_project`。
   收緊 `networkPolicy`（設 `allowFromAllNamespaces: false`）或把 Service 的
   `mcp` 埠拿掉才是解法。
5. **probe 只看 8080。** supergateway 自己的 `/healthz`（8000）沒有被 probe，
   它 hang 住而沒有退出時不會被偵測到。
6. **`localhost/od-mcp:latest` 無法重現。** 沒有 CI、沒有 registry、沒有 tag，
   線上的 image 追不回是哪一個 commit。`image.mode: source` 只是繞路，把 image
   發布出去才是解法。
