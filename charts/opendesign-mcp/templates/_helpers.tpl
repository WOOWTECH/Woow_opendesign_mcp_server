{{/*
Helpers for the opendesign-mcp chart.

Object names are derived from fullnameOverride (default "od-mcp") and NOT from
the release name: the selector and the pod-template label are built from it, so
deriving them from .Release.Name would restart the running pod the first time
the live instance is taken over by Helm. One release per instance; give a second
instance its own fullnameOverride.
*/}}

{{- define "odmcp.fullname" -}}
{{- default "od-mcp" .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- /*
Object placement. `namespace.name` is EMPTY by default so placement follows
`-n`/`--namespace`. Setting it wins over `-n`, so a `-n <test-ns> -f <real
instance values>` rehearsal would write to the REAL namespace. Never set it
in a committed instance values file.
*/ -}}
{{- define "odmcp.ns" -}}
{{ .Values.namespace.name | default .Release.Namespace }}
{{- end -}}

{{/* Selector / pod-template label. Changing it re-creates the ReplicaSet. */}}
{{- define "odmcp.selectorLabels" -}}
app: {{ include "odmcp.fullname" . }}
{{- end -}}

{{/* Object labels, exactly the two the live objects carry. */}}
{{- define "odmcp.labels" -}}
app: {{ include "odmcp.fullname" . }}
app.kubernetes.io/part-of: {{ .Values.partOf }}
{{- end -}}

{{/* `annotations:` block with the keep policy, or nothing. */}}
{{- define "odmcp.keepAnnotations" -}}
{{- if .Values.keepOnUninstall -}}
annotations:
  helm.sh/resource-policy: keep
{{- end -}}
{{- end -}}

{{- define "odmcp.secretName" -}}
{{- default (printf "%s-secrets" (include "odmcp.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "odmcp.pvcName" -}}
{{- default (printf "%s-data" (include "odmcp.fullname" .)) .Values.persistence.existingClaim -}}
{{- end -}}

{{- define "odmcp.namespaceEnv" -}}
{{- default (include "odmcp.ns" .) .Values.env.namespace -}}
{{- end -}}

{{/* Image reference for the workload container. */}}
{{- define "odmcp.image" -}}
{{- if eq .Values.image.mode "source" -}}
{{ .Values.source.images.runtime }}
{{- else -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}
{{- end -}}

{{- define "odmcp.imagePullPolicy" -}}
{{- if eq .Values.image.mode "source" -}}
IfNotPresent
{{- else -}}
{{ .Values.image.pullPolicy }}
{{- end -}}
{{- end -}}

{{/* Image the `helm test` pod runs. It only needs python3. */}}
{{- define "odmcp.testImage" -}}
{{- default (include "odmcp.image" .) .Values.tests.image -}}
{{- end -}}

{{/* Fail early on an unknown image.mode instead of rendering a broken pod. */}}
{{- define "odmcp.validate" -}}
{{- if not (has .Values.image.mode (list "prebuilt" "source")) -}}
{{- fail (printf "image.mode must be \"prebuilt\" or \"source\", got %q" .Values.image.mode) -}}
{{- end -}}
{{- end -}}
