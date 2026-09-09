package main

deny contains msg if {
	input.apiVersion == "route.openshift.io/v1"
	msg := "OpenShift Route is not supported on AKS; use networking.k8s.io/v1 Ingress"
}

deny contains msg if {
	input.apiVersion == "autoscaling/v1"
	input.kind == "HorizontalPodAutoscaler"
	msg := "autoscaling/v1 HPA is deprecated; use autoscaling/v2 with a metrics block"
}

deny contains msg if {
	input.kind == "Deployment"
	c := input.spec.template.spec.containers[_]
	not c.resources.limits
	msg := sprintf("container %q has no resource limits", [c.name])
}

warn contains msg if {
	input.kind == "Deployment"
	c := input.spec.template.spec.containers[_]
	not c.readinessProbe
	msg := sprintf("container %q has no readinessProbe; --atomic rollback is unreliable", [c.name])
}

warn contains msg if {
	input.kind == "Ingress"
	not input.spec.ingressClassName
	msg := "Ingress has no ingressClassName"
}