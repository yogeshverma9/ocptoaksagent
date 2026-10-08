-include migration.env

IMAGE ?= aks-migrator:latest
REPO ?= $(if $(wildcard ocp),$(PWD)/ocp,$(PWD)/workspace)
OUT_DIR ?= $(PWD)/aks
CONFIG_DIR ?= $(PWD)/config
# Blank by default - migrate converts every environment in
# config/env-matrix.yaml in one pass when ENV isn't set. Set ENV=<name> to
# restrict a run to just one.
ENV ?=
MODE ?= offline
FAIL_ON_BLOCK ?= true
WORKBOOK_INTAKE ?= $(PWD)/migration-intake.example.txt

# LLM is mandatory (config/models.yaml, default provider: ollama - local,
# no API key). "localhost" from inside the container is the container
# itself, so the default endpoint targets Docker Desktop's host gateway.
LLM_ENDPOINT ?= http://host.docker.internal:11434
LLM_MODEL ?=
LLM_SEED ?=
LLM_TIMEOUT ?=
FREEZE_OUTPUT ?= false
LLM_FORCE_REFRESH ?= false
LLM_CACHE_DIR ?=

ifeq ($(strip $(FAIL_ON_BLOCK)),false)
FAIL_FLAG := --no-fail-on-block
else
FAIL_FLAG := --fail-on-block
endif

# Emits --env <name> only if ENV is actually set - omitting it entirely
# tells aks-migrator to convert every environment in config/env-matrix.yaml
# in one pass, rather than defaulting to one.
ifneq ($(strip $(ENV)),)
ENV_FLAG := --env $(ENV)
else
ENV_FLAG :=
endif

LLM_ARGS := --add-host=host.docker.internal:host-gateway \
	-e LLM_ENDPOINT=$(LLM_ENDPOINT) -e FREEZE_OUTPUT=$(FREEZE_OUTPUT) \
	-e LLM_FORCE_REFRESH=$(LLM_FORCE_REFRESH)
ifneq ($(strip $(LLM_MODEL)),)
LLM_ARGS += -e LLM_MODEL=$(LLM_MODEL)
endif
ifneq ($(strip $(LLM_SEED)),)
LLM_ARGS += -e LLM_SEED=$(LLM_SEED)
endif
ifneq ($(strip $(LLM_TIMEOUT)),)
LLM_ARGS += -e LLM_TIMEOUT=$(LLM_TIMEOUT)
endif
ifneq ($(strip $(LLM_CACHE_DIR)),)
LLM_ARGS += -e LLM_CACHE_DIR=$(LLM_CACHE_DIR)
endif

.PHONY: build migrate workbook test shell clean

build:
	docker build -t $(IMAGE) .

## Run against a real checkout or copy migration.env.example to migration.env
## and set REPO=/path/to/repo (or REPO=<git-url> - clone it yourself first;
## Makefile does not auto-clone, use ./run.sh for that convenience).
migrate: build
	mkdir -p $(OUT_DIR)
	docker run --rm \
		-v $(REPO):/workspace:ro \
		-v $(OUT_DIR):/aks \
		-v $(CONFIG_DIR):/config:ro \
		$(LLM_ARGS) \
		--env-file .env \
		$(IMAGE) migrate \
			--repo $(notdir $(REPO)) \
			$(ENV_FLAG) \
			--mode $(MODE) \
			--out /aks \
			$(FAIL_FLAG)

## Build the migration workbook from a text intake file: make workbook WORKBOOK_INTAKE=/path/to/intake.txt
workbook: build
	mkdir -p $(OUT_DIR)
	docker run --rm \
		-v $(WORKBOOK_INTAKE):/intake.txt:ro \
		-v $(OUT_DIR):/aks \
		-v $(CONFIG_DIR):/config:ro \
		$(IMAGE) workbook \
			--intake /intake.txt \
			--out /aks

test: build
	docker run --rm $(LLM_ARGS) $(IMAGE) selftest

shell: build
	docker run --rm -it --entrypoint /bin/bash \
		-v $(PWD):/app -v $(OUT_DIR):/aks $(IMAGE)

clean:
	rm -rf $(OUT_DIR)