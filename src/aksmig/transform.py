from __future__ import annotations

import re
from typing import Any

from .discovery import Inventory
from .models import Finding, Severity

INGRESS_TEMPLATE = """apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
{annotations}
  labels:
    app: {{{{ .Values.service.label }}}}
  name: {name}
  namespace: {{{{ .Values.deployment.namespace }}}}
spec:
  ingressClassName: {ingress_class}
{tls_block}  rules:
    - host: {{{{ .Values.route.host }}}}
      http:
        paths:
          - path: {path}
            pathType: Prefix
            backend:
              service:
                name: {service_name}
                port:
                  number: {{{{ .Values.service.portValue }}}}
"""

INGRESS_TLS_BLOCK = """  tls:
    - hosts:
        - {{{{ .Values.route.host }}}}
      secretName: {secret_name}
"""

HPA_V2_TEMPLATE = """apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {name}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {name}
  minReplicas: {{{{ .Values.hpa.minReplicas }}}}
  maxReplicas: {{{{ .Values.hpa.maxReplicas }}}}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{{{ .Values.hpa.targetCPUUtilizationPercentage }}}}
"""

DEPLOY_TEMPLATE = """parameters:
  - name: buildNumber
    type: string
    default: latest
  - name: environment
    type: string
  - name: azureSubscription
    type: string
  - name: azureResourceGroup
    type: string
  - name: aksTargetClusterName
    type: string
  - name: kubernetesNamespace
    type: string
  - name: values
    type: string

jobs:
  - deployment: Deploy
    displayName: Deploy to ${{{{ parameters.environment }}}}
    pool:
      name: {pool}
    timeoutInMinutes: 0
    cancelTimeoutInMinutes: 0
    environment: ${{{{ parameters.environment }}}}
    strategy:
      runOnce:
        deploy:
          steps:
            - checkout: self
              clean: true

            - task: AzureCLI@2
              displayName: "Login + Get AKS Credentials"
              inputs:
                azureSubscription: ${{{{ parameters.azureSubscription }}}}
                scriptType: bash
                scriptLocation: inlineScript
                inlineScript: |
                  az account show --query user
                  az aks get-credentials \\
                    --resource-group ${{{{ parameters.azureResourceGroup }}}} \\
                    --name ${{{{ parameters.aksTargetClusterName }}}} \\
                    --overwrite-existing
                  kubelogin convert-kubeconfig -l azurecli
                  kubectl get pods --namespace ${{{{ parameters.kubernetesNamespace }}}} --request-timeout=30s

            - task: AzureCLI@2
              displayName: "Validate RBAC Permissions"
              inputs:
                azureSubscription: ${{{{ parameters.azureSubscription }}}}
                scriptType: bash
                scriptLocation: inlineScript
                inlineScript: |
                  kubectl auth can-i create pods --namespace ${{{{ parameters.kubernetesNamespace }}}} \\
                    && echo "OK: can create pods" \\
                    || {{ echo "FAIL: insufficient permissions"; exit 1; }}

            - task: AzureCLI@2
              displayName: "Resolve Image Tag"
              name: SetTagId
              inputs:
                azureSubscription: ${{{{ parameters.azureSubscription }}}}
                scriptType: bash
                scriptLocation: inlineScript
                inlineScript: |
                  az extension add --name azure-devops --allow-preview true

                  if [ "${{{{ parameters.buildNumber }}}}" == "latest" ]; then
                    tag=$(az pipelines runs list \\
                      --project "$(System.TeamProject)" \\
                      --output json --result succeeded --tags Built \\
                      --branch ${{{{ replace(variables['Build.SourceBranch'], 'refs/heads/', '') }}}} \\
                      --query-order FinishTimeDesc --top 1 | jq -r '.[0].buildNumber')
                    if [ "$tag" == "null" ] || [ -z "$tag" ]; then
                      tag=$(az pipelines runs list \\
                        --project "$(System.TeamProject)" \\
                        --output json --result succeeded --tags Built \\
                        --branch master --query-order FinishTimeDesc --top 1 | jq -r '.[0].buildNumber')
                    fi
                  else
                    tag="${{{{ parameters.buildNumber }}}}"
                  fi

                  if [ "$tag" == "null" ] || [ -z "$tag" ]; then
                    echo "Build tag could not be found"
                    exit 1
                  fi
                  echo "Resolved image tag: $tag"
                  echo "##vso[task.setVariable variable=tag;isOutput=true]$tag"
              env:
                AZURE_DEVOPS_EXT_PAT: $(System.AccessToken)

            - task: AzureCLI@2
              displayName: "Helm Dry Run"
              inputs:
                azureSubscription: ${{{{ parameters.azureSubscription }}}}
                scriptType: bash
                scriptLocation: inlineScript
                inlineScript: |
                  helm upgrade {release} $(Build.SourcesDirectory)/helm/ \\
                    --install \\
                    --namespace ${{{{ parameters.kubernetesNamespace }}}} \\
                    --values $(Build.SourcesDirectory)/helm/${{{{ parameters.values }}}} \\
                    --set image.tag=$(SetTagId.tag) \\
                    --dry-run --debug

            - task: AzureCLI@2
              displayName: "Helm Upgrade"
              inputs:
                azureSubscription: ${{{{ parameters.azureSubscription }}}}
                scriptType: bash
                scriptLocation: inlineScript
                inlineScript: |
                  helm upgrade {release} $(Build.SourcesDirectory)/helm/ \\
                    --install \\
                    --namespace ${{{{ parameters.kubernetesNamespace }}}} \\
                    --values $(Build.SourcesDirectory)/helm/${{{{ parameters.values }}}} \\
                    --set image.tag=$(SetTagId.tag) \\
                    --atomic --timeout 15m0s --history-max 3
"""


class TransformResult:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.deleted: list[str] = []
        self.findings: list[Finding] = []


def _memory_units(text: str) -> tuple[str, int]:
    pattern = re.compile(r'(memory:\s*"?)(\d+)([MG])("?)(?!i)')
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}{m.group(2)}{m.group(3)}i{m.group(4)}"

    return pattern.sub(sub, text), count


def transform(inv: Inventory, cfg, env: dict[str, Any]) -> TransformResult:
    res = TransformResult()
    std = cfg.standards
    tier = env.get("tier", env["name"])
    ingress_class = std["ingress"]["class"]

    # A file that matches a specific environment's `valuesFile` (see
    # config/env-matrix.yaml) belongs to that environment even when other
    # environments' values files live side by side in the same chart -
    # T6 (DNS remap) below uses this to resolve the correct tier per file,
    # rather than applying the single passed-in `env`'s tier to everything.
    envs_by_values_file = {
        e["valuesFile"]: e for e in cfg.env_matrix.get("environments", []) if e.get("valuesFile")
    }

    # ---- start from the source tree
    for rel in inv.files:
        res.files[rel] = inv.text(rel)

    # ---- T1 route -> ingress
    for rel in list(res.files):
        if "route.openshift.io/v1" not in res.files[rel]:
            continue
        text = res.files[rel]
        name = re.search(r"^\s*name:\s*([\w.-]+)", text, re.M)
        svc = re.search(r"to:\s*\n\s*kind:\s*Service\s*\n\s*name:\s*([\w.-]+)", text)

        # Route.spec.path (defaults to "/" if unset, same as OpenShift's own default).
        path_m = re.search(r"^\s*path:\s*(\S+)", text, re.M)
        route_path = path_m.group(1).strip('"') if path_m else "/"

        # Route.spec.tls: any termination type means the Route was serving HTTPS.
        # We cannot know the AKS-side secret name automatically, so surface it as
        # NEEDS_INPUT rather than silently downgrading to plain HTTP.
        tls_m = re.search(r"^\s*tls:\s*\n(?:\s+\S.*\n?)+", text, re.M)
        tls_block = ""
        if tls_m:
            tls_block = INGRESS_TLS_BLOCK.format(
                secret_name='{{ .Values.route.tlsSecretName }}')
            res.findings.append(
                Finding("T1", "Route TLS termination requires a secretName",
                        Severity.NEEDS_INPUT, rel,
                        "The source Route specified TLS. The emitted Ingress references "
                        ".Values.route.tlsSecretName, which is not yet defined.",
                        remediation="Provision/import the TLS secret on AKS and set "
                                    "route.tlsSecretName in the environment's values file."))

        anns = {**std["ingress"].get("requiredAnnotations", {})}
        for review in std["ingress"].get("reviewAnnotations", []):
            m = re.search(rf"{re.escape(review)}:\s*(\S+)", text)
            if m:
                # These are OpenShift Route-specific annotation keys (haproxy.router.openshift.io/*).
                # The target ingress controller will not recognise the same key, so the value
                # cannot be safely carried over as-is; flag it for manual translation instead
                # of silently dropping or mis-copying it.
                res.findings.append(
                    Finding("T1", f"Route annotation {review!r} needs manual translation",
                            Severity.NEEDS_INPUT, rel,
                            f"Value {m.group(1)!r} was set on the OpenShift Route. The AKS "
                            f"ingress controller ({ingress_class}) does not use this annotation "
                            "key; find the equivalent and set it explicitly.",
                            remediation=f"Translate {review} -> the {ingress_class} equivalent "
                                        "annotation in the emitted Ingress."))
        ann_block = "\n".join(f'    {k}: "{v}"'.replace('""', '"') for k, v in anns.items())

        target = rel.replace("route.yaml", "ingress.yaml").replace("route.yml", "ingress.yaml")
        res.files[target] = INGRESS_TEMPLATE.format(
            annotations=ann_block or "    {}",
            name=name.group(1) if name else "app-ingress",
            ingress_class=ingress_class,
            tls_block=tls_block,
            path=route_path,
            service_name=svc.group(1) if svc else "app-service",
        )
        res.deleted.append(rel)
        del res.files[rel]
        res.findings.append(
            Finding("T1", "Route converted to Ingress", Severity.INFO, rel,
                    f"Emitted {target} with ingressClassName={ingress_class}",
                    auto_fixed=True))

    # ---- T3 hpa v1 -> v2
    for rel, text in list(res.files.items()):
        if "autoscaling/v1" not in text or "HorizontalPodAutoscaler" not in text:
            continue
        name = re.search(r"^\s*name:\s*(\{\{.*?\}\}|[\w.-]+)", text, re.M)
        res.files[rel] = HPA_V2_TEMPLATE.format(name=name.group(1) if name else "app")
        res.findings.append(
            Finding("T3", "HPA upgraded to autoscaling/v2", Severity.INFO, rel,
                    "Replaced targetCPUUtilizationPercentage with a metrics block",
                    auto_fixed=True))

    # ---- T4 memory units
    for rel, text in list(res.files.items()):
        new, n = _memory_units(text)
        if n:
            res.files[rel] = new
            res.findings.append(
                Finding("T4", "Memory units normalised to binary", Severity.INFO, rel,
                        f"Converted {n} decimal memory value(s) to Mi/Gi", auto_fixed=True))

    # ---- T6 dns remap (templates, values and pipelines alike)
    # An empty legacyPattern means DNS remapping is deliberately disabled -
    # skip cleanly rather than compiling an empty regex, which would
    # zero-width-match everything and then fail on the named-group lookup.
    legacy_dns_pattern = std["dns"].get("legacyPattern")
    if legacy_dns_pattern:
        dns_re = re.compile(legacy_dns_pattern)
        for rel, text in list(res.files.items()):
            matches = list(dns_re.finditer(text))
            if not matches:
                continue
            # Use the specific environment this file belongs to (matched by
            # valuesFile) when one exists, so converting several environments'
            # values files in one pass remaps each to its own tier - falling
            # back to the primary/passed-in environment for files that aren't
            # a specific environment's values file (pipeline files, etc.).
            file_env = envs_by_values_file.get(rel.rsplit("/", 1)[-1])
            file_tier = file_env.get("tier", file_env["name"]) if file_env else tier
            new = text
            example_target = None
            for m in matches:
                target = std["dns"]["targetTemplate"].format(app=m.group("app"), tier=file_tier)
                example_target = example_target or target
                new = new.replace(m.group(0), target)
            res.files[rel] = new
            res.findings.append(
                Finding("T6", "OCP hostnames remapped to AKS", Severity.INFO, rel,
                        f"Rewrote {len(matches)} host(s) using the configured DNS target "
                        f"template (standards.yaml dns.targetTemplate) for tier {file_tier!r}, "
                        f"e.g. {example_target}",
                        auto_fixed=True))

    # ---- T2 + T5 + T7 pipeline rewrite
    for rel, text in list(res.files.items()):
        if "HelmDeploy@0" not in text and "kubernetesServiceEndpoint" not in text:
            continue
        # Guard against rewriting the wrong file: a multi-stage pipeline root
        # (top-level `stages:`) may reference these strings inside a legacy/unused
        # stage, but only a single-job deploy template (top-level `jobs:` with a
        # `- deployment:` job, no `stages:`) is safe to replace wholesale. Without
        # this check, files like azure-pipelines.yml get destructively overwritten
        # even though only one of their several stages is deploy-related.
        has_stages = bool(re.search(r"^stages:\s*$", text, re.M))
        has_deploy_job = bool(re.search(r"^\s*-\s*deployment:", text, re.M))
        if has_stages or not has_deploy_job:
            res.findings.append(
                Finding("T2", "Skipped HelmDeploy@0 rewrite: file is not a single deploy-job template",
                        Severity.NEEDS_INPUT, rel,
                        "This file contains HelmDeploy@0/kubernetesServiceEndpoint but has a "
                        "top-level 'stages:' key (or no single 'deployment:' job), so it was left "
                        "unmodified to avoid destroying unrelated stages. Update it by hand, or "
                        "confirm it is dead/unused.",
                        remediation="Manually migrate this file's deploy step(s), or delete it "
                                    "if superseded by pipeline/deploy.yaml."))
            continue
        release = re.search(r"releaseName:\s*([\w.-]+)", text)
        pool = env.get("agentPool", std["pipeline"]["agentPools"]["nonProduction"])
        res.files[rel] = DEPLOY_TEMPLATE.format(
            pool=pool, release=release.group(1) if release else "app-release")
        res.findings.append(
            Finding("T2", "HelmDeploy@0 replaced with AzureCLI@2 + helm CLI",
                    Severity.INFO, rel,
                    "Now uses az aks get-credentials + kubelogin, with dry-run and RBAC preflight",
                    auto_fixed=True))
        res.findings.append(
            Finding("T5", "Agent pool remapped", Severity.INFO, rel,
                    f"Pool set to {pool}", auto_fixed=True))
        res.findings.append(
            Finding("T7", "Service connection expanded to explicit AKS targeting",
                    Severity.INFO, rel,
                    "azureSubscription / azureResourceGroup / aksTargetClusterName / kubernetesNamespace",
                    auto_fixed=True))

    # ---- forbidden pools anywhere else
    default_pool = std["pipeline"]["agentPools"]["nonProduction"]
    replacement_pool = env.get("agentPool") or default_pool
    for rel, text in list(res.files.items()):
        for bad in std["pipeline"].get("forbiddenPools", []):
            if bad in text:
                res.files[rel] = text.replace(bad, replacement_pool)
                res.findings.append(
                    Finding("T5", "Forbidden agent pool replaced", Severity.INFO, rel,
                            f"{bad} -> {replacement_pool}", auto_fixed=True))
                if not env.get("agentPool"):
                    res.findings.append(
                        Finding("N0", f"Environment {env['name']} has no agentPool configured",
                                Severity.NEEDS_INPUT, "config/env-matrix.yaml",
                                f"Fell back to default pool {default_pool!r}; confirm this is correct.",
                                remediation=f"Set agentPool for environment {env['name']}."))

    # ---- T8 CD stage orchestrator: propagate deploy.yaml's new parameter contract
    # into every stage that instantiates it via `template: deploy.yaml`. T2 rewrites
    # deploy.yaml's own parameter list (endpoint -> azureSubscription/azureResourceGroup/
    # aksTargetClusterName/kubernetesNamespace); without this, any file that calls
    # deploy.yaml as a template is left passing the old `endpoint` parameter, which the
    # rewritten deploy.yaml no longer declares.
    all_envs = envs_by_values_file
    for rel, text in list(res.files.items()):
        if "template: deploy.yaml" not in text and "template: deploy.yml" not in text:
            continue
        if "endpoint:" not in text:
            continue  # already on the new contract, or not applicable

        blocks = re.split(r"(?=^- stage:)", text, flags=re.M)
        new_blocks: list[str] = []
        rewritten_any = False
        for block in blocks:
            values_m = re.search(r"^\s*values:\s*(\S+)", block, re.M)
            endpoint_m = re.search(r"^(\s*)endpoint:\s*\S+\s*$", block, re.M)
            if not (values_m and endpoint_m):
                new_blocks.append(block)
                continue
            target_env = all_envs.get(values_m.group(1))
            if not target_env:
                res.findings.append(
                    Finding("T8", f"Could not map values file {values_m.group(1)!r} to an environment",
                            Severity.NEEDS_INPUT, rel,
                            "No env-matrix.yaml entry has this valuesFile; the stage's "
                            "deploy.yaml parameters could not be rewritten automatically.",
                            remediation="Add/correct the matching valuesFile entry in env-matrix.yaml, "
                                        "or update this stage's parameters by hand."))
                new_blocks.append(block)
                continue

            indent = endpoint_m.group(1)
            replacement = (
                f"{indent}azureSubscription: {target_env['azureSubscription']}\n"
                f"{indent}azureResourceGroup: {target_env['azureResourceGroup']}\n"
                f"{indent}aksTargetClusterName: {target_env['aksTargetClusterName']}\n"
                f"{indent}kubernetesNamespace: {target_env['kubernetesNamespace']}"
            )
            block = block[:endpoint_m.start()] + replacement + block[endpoint_m.end():]
            # Add a stage-level pool if this stage doesn't already declare one.
            if not re.search(r"^\s*pool:\s*$", block, re.M) and re.search(r"^-\s*stage:", block, re.M):
                stage_m = re.search(r"^(-\s*stage:.*\n)", block, re.M)
                if stage_m:
                    pool_line = f"  pool:\n    name: {target_env.get('agentPool') or default_pool}\n"
                    block = block[:stage_m.end()] + pool_line + block[stage_m.end():]
            new_blocks.append(block)
            rewritten_any = True

        if rewritten_any:
            res.files[rel] = "".join(new_blocks)
            res.findings.append(
                Finding("T8", "CD stage parameters updated for deploy.yaml's new contract",
                        Severity.INFO, rel,
                        "Replaced endpoint: with azureSubscription/azureResourceGroup/"
                        "aksTargetClusterName/kubernetesNamespace, and added a stage pool.",
                        auto_fixed=True))
            # A top-level `parameters:` block (buildNumber) is required by ADO whenever a
            # stage references ${{ parameters.buildNumber }}; add it if missing.
            if "parameters:" not in res.files[rel].split("stages:")[0] and \
                    "parameters.buildNumber" in res.files[rel]:
                res.files[rel] = (
                    "parameters:\n"
                    "  - name: buildNumber\n"
                    "    type: string\n"
                    "    default: latest\n\n" + res.files[rel]
                )
                res.findings.append(
                    Finding("T8", "Added missing top-level buildNumber parameter",
                            Severity.INFO, rel,
                            "The file referenced ${{ parameters.buildNumber }} without declaring it.",
                            auto_fixed=True))

    return res