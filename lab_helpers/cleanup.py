"""Cleanup helpers used by Lab 7 to delete every AWS resource created by the labs.

Each function only touches resources created by this workshop, looked up by
their well-known names or by the IDs the labs stored in SSM Parameter Store.
Missing resources are skipped, so the cleanup is safe to run even if some
(optional) labs were never executed, or if it is run more than once.
"""

import json
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from lab_helpers.utils import (
    GATEWAY_LAMBDA_NAME,
    GATEWAY_LAMBDA_ROLE_NAME,
    GATEWAY_ROLE_NAME,
    REGION,
    delete_agentcore_runtime_execution_role,
    delete_customer_support_secret,
    get_customer_support_secret,
    get_kb_resource_names,
    get_ssm_parameter,
)

SSM_PREFIX = "/app/customersupport"
AGENT_NAME = "customer_support_agent"
GATEWAY_NAME = "customersupport-gw"
POLICY_ENGINE_NAME = "customersupport_pe"
MEMORY_NAME = "CustomerSupportMemory"
COGNITO_POOL_NAME = "customersupport-user-pool"
EVAL_CONFIG_NAME = "customer_support_agent_eval"
OAUTH2_PROVIDERS = ["customersupport-google-calendar", "customersupport-gateways-cognito"]
OBSERVABILITY_LOG_GROUP = "agents/customer-support-assistant-logs"
LOCAL_FILES = ["Dockerfile", ".dockerignore", ".bedrock_agentcore.yaml", "customer_support_agent.py", "observability.env"]

control = boto3.client("bedrock-agentcore-control", region_name=REGION)


def _not_found(error: ClientError) -> bool:
    code = error.response["Error"]["Code"]
    return code in ("ResourceNotFoundException", "NoSuchEntity", "NoSuchEntityException", "ParameterNotFound")


def _ssm(name: str):
    try:
        return get_ssm_parameter(f"{SSM_PREFIX}/agentcore/{name}")
    except ClientError:
        return None


def _wait_until_gone(describe, what: str, timeout: int = 180) -> None:
    """Poll `describe()` until it raises ResourceNotFoundException."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            describe()
        except ClientError as e:
            if _not_found(e):
                return
            raise
        time.sleep(5)
    print(f"  ⚠️ Timed out waiting for {what} to be deleted")


def _delete_role(role_name: str) -> None:
    iam = boto3.client("iam")
    try:
        for policy in iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]:
            iam.detach_role_policy(RoleName=role_name, PolicyArn=policy["PolicyArn"])
        for policy_name in iam.list_role_policies(RoleName=role_name)["PolicyNames"]:
            iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
        iam.delete_role(RoleName=role_name)
        print(f"  ✅ Deleted IAM role {role_name}")
    except ClientError as e:
        if not _not_found(e):
            raise
        print(f"  ℹ️ IAM role {role_name} not found")


def _delete_log_groups(prefix: str) -> None:
    logs = boto3.client("logs", region_name=REGION)
    for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
        for group in page["logGroups"]:
            logs.delete_log_group(logGroupName=group["logGroupName"])
            print(f"  ✅ Deleted log group {group['logGroupName']}")


# ---------------------------------------------------------------------------
# Lab 5: online evaluation
# ---------------------------------------------------------------------------


def delete_online_evaluation() -> None:
    from bedrock_agentcore_starter_toolkit import Evaluation

    eval_client = Evaluation(region=REGION)
    configs = eval_client.list_online_configs().get("onlineEvaluationConfigs", [])
    ours = [c for c in configs if c.get("onlineEvaluationConfigName") == EVAL_CONFIG_NAME]
    if not ours:
        print(f"  ℹ️ Online evaluation config {EVAL_CONFIG_NAME} not found")
    for config in ours:
        # Also deletes the IAM execution role auto-created in Lab 5
        eval_client.delete_online_config(config["onlineEvaluationConfigId"], delete_execution_role=True)


# ---------------------------------------------------------------------------
# Lab 4: AgentCore Runtime
# ---------------------------------------------------------------------------


def delete_runtime() -> None:
    """Delete the runtime, its endpoint, ECR repository, CodeBuild project, logs and execution role."""
    runtime_arn = _ssm("runtime_arn")
    runtime_id = runtime_arn.split("/")[-1] if runtime_arn else None

    config_path = Path(".bedrock_agentcore.yaml")
    if config_path.exists():
        # The starter toolkit knows every resource it created during configure/launch
        from bedrock_agentcore_starter_toolkit import Runtime

        runtime = Runtime()
        runtime._config_path = config_path.resolve()
        runtime.name = AGENT_NAME
        result = runtime.destroy(delete_ecr_repo=True)
        for resource in result.resources_removed:
            print(f"  ✅ Deleted {resource}")
        for warning in result.warnings:
            print(f"  ℹ️ {warning}")
        for error in result.errors:
            print(f"  ⚠️ {error}")
    else:
        # Fallback when the local toolkit configuration is gone: delete by name
        print("  ℹ️ .bedrock_agentcore.yaml not found, deleting the runtime by name")
        runtimes = control.list_agent_runtimes(maxResults=100)["agentRuntimes"]
        for rt in [r for r in runtimes if r["agentRuntimeName"] == AGENT_NAME]:
            runtime_id = rt["agentRuntimeId"]
            control.delete_agent_runtime(agentRuntimeId=runtime_id)
            print(f"  ✅ Deleted agent runtime {runtime_id}")
        ecr = boto3.client("ecr", region_name=REGION)
        try:
            ecr.delete_repository(repositoryName=f"bedrock-agentcore-{AGENT_NAME}", force=True)
            print(f"  ✅ Deleted ECR repository bedrock-agentcore-{AGENT_NAME}")
        except ecr.exceptions.RepositoryNotFoundException:
            pass

    if runtime_id:
        _delete_log_groups(f"/aws/bedrock-agentcore/runtimes/{runtime_id}")
    delete_agentcore_runtime_execution_role()


# ---------------------------------------------------------------------------
# Lab 3: AgentCore Gateway, Policy and the tools Lambda
# ---------------------------------------------------------------------------


def delete_gateway() -> None:
    gateways = [g for g in control.list_gateways(maxResults=100)["items"] if g["name"] == GATEWAY_NAME]
    if not gateways:
        print(f"  ℹ️ Gateway {GATEWAY_NAME} not found")
    for gateway in gateways:
        gateway_id = gateway["gatewayId"]
        targets = control.list_gateway_targets(gatewayIdentifier=gateway_id, maxResults=100)["items"]
        for target in targets:
            control.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target["targetId"])
            print(f"  ✅ Deleted gateway target {target['targetId']}")
        deadline = time.time() + 120
        while control.list_gateway_targets(gatewayIdentifier=gateway_id)["items"] and time.time() < deadline:
            time.sleep(5)

        control.delete_gateway(gatewayIdentifier=gateway_id)
        _wait_until_gone(lambda: control.get_gateway(gatewayIdentifier=gateway_id), f"gateway {gateway_id}")
        print(f"  ✅ Deleted gateway {gateway_id}")


def delete_policy_engine() -> None:
    engines = [e for e in control.list_policy_engines()["policyEngines"] if e["name"] == POLICY_ENGINE_NAME]
    if not engines:
        print(f"  ℹ️ Policy engine {POLICY_ENGINE_NAME} not found")
    for engine in engines:
        engine_id = engine["policyEngineId"]
        for policy in control.list_policies(policyEngineId=engine_id, maxResults=100)["policies"]:
            control.delete_policy(policyEngineId=engine_id, policyId=policy["policyId"])
            print(f"  ✅ Deleted policy {policy['name']}")
        deadline = time.time() + 120
        while control.list_policies(policyEngineId=engine_id)["policies"] and time.time() < deadline:
            time.sleep(5)

        control.delete_policy_engine(policyEngineId=engine_id)
        _wait_until_gone(lambda: control.get_policy_engine(policyEngineId=engine_id), f"policy engine {engine_id}")
        print(f"  ✅ Deleted policy engine {engine_id}")


def delete_gateway_tools() -> None:
    """Delete the tools Lambda, its logs and the two IAM roles created in Lab 3."""
    lambda_client = boto3.client("lambda", region_name=REGION)
    try:
        lambda_client.delete_function(FunctionName=GATEWAY_LAMBDA_NAME)
        print(f"  ✅ Deleted Lambda function {GATEWAY_LAMBDA_NAME}")
    except lambda_client.exceptions.ResourceNotFoundException:
        print(f"  ℹ️ Lambda function {GATEWAY_LAMBDA_NAME} not found")
    _delete_log_groups(f"/aws/lambda/{GATEWAY_LAMBDA_NAME}")
    _delete_role(GATEWAY_ROLE_NAME)
    _delete_role(GATEWAY_LAMBDA_ROLE_NAME)


# ---------------------------------------------------------------------------
# Optional Identity lab: OAuth2 credential providers
# ---------------------------------------------------------------------------


def delete_oauth2_providers() -> None:
    for name in OAUTH2_PROVIDERS:
        try:
            control.delete_oauth2_credential_provider(name=name)
            print(f"  ✅ Deleted OAuth2 credential provider {name}")
        except ClientError as e:
            if not _not_found(e):
                raise
            print(f"  ℹ️ OAuth2 credential provider {name} not found")


# ---------------------------------------------------------------------------
# Lab 3: Cognito user pool and the Secrets Manager secret
# ---------------------------------------------------------------------------


def delete_cognito() -> None:
    cognito = boto3.client("cognito-idp", region_name=REGION)

    pool_ids = set()
    secret = get_customer_support_secret()
    if secret:
        pool_ids.add(json.loads(secret)["pool_id"])
    for page in cognito.get_paginator("list_user_pools").paginate(MaxResults=60):
        pool_ids.update(p["Id"] for p in page["UserPools"] if p["Name"] == COGNITO_POOL_NAME)

    if not pool_ids:
        print(f"  ℹ️ Cognito user pool {COGNITO_POOL_NAME} not found")
    for pool_id in pool_ids:
        try:
            # A user pool with a domain (optional Identity lab) can't be deleted
            domain = cognito.describe_user_pool(UserPoolId=pool_id)["UserPool"].get("Domain")
            if domain:
                cognito.delete_user_pool_domain(Domain=domain, UserPoolId=pool_id)
                print(f"  ✅ Deleted Cognito domain {domain}")
            cognito.delete_user_pool(UserPoolId=pool_id)
            print(f"  ✅ Deleted Cognito user pool {pool_id}")
        except cognito.exceptions.ResourceNotFoundException:
            print(f"  ℹ️ Cognito user pool {pool_id} not found")

    if secret:
        delete_customer_support_secret()


# ---------------------------------------------------------------------------
# Lab 2: AgentCore Memory
# ---------------------------------------------------------------------------


def delete_memory() -> None:
    memory_ids = {m["id"] for m in control.list_memories(maxResults=100)["memories"] if m["id"].startswith(f"{MEMORY_NAME}-")}
    if not memory_ids:
        print(f"  ℹ️ Memory {MEMORY_NAME} not found")
    for memory_id in memory_ids:
        try:
            control.delete_memory(memoryId=memory_id)
            print(f"  ✅ Deleted memory {memory_id}")
        except ClientError as e:
            if not _not_found(e):
                raise


# ---------------------------------------------------------------------------
# Lab 1: Amazon Bedrock Knowledge Base
# ---------------------------------------------------------------------------


def delete_knowledge_base() -> None:
    """Delete the data source, Knowledge Base, vector index and bucket, documents bucket and IAM role."""
    names = get_kb_resource_names()
    bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)

    kbs = [
        kb
        for kb in bedrock_agent.list_knowledge_bases(maxResults=100)["knowledgeBaseSummaries"]
        if kb["name"] == names["knowledge_base"]
    ]
    if not kbs:
        print(f"  ℹ️ Knowledge Base {names['knowledge_base']} not found")
    for kb in kbs:
        kb_id = kb["knowledgeBaseId"]
        for ds in bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]:
            bedrock_agent.delete_data_source(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"])
            _wait_until_gone(
                lambda: bedrock_agent.get_data_source(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"]),
                f"data source {ds['dataSourceId']}",
            )
            print(f"  ✅ Deleted data source {ds['dataSourceId']}")
        bedrock_agent.delete_knowledge_base(knowledgeBaseId=kb_id)
        _wait_until_gone(lambda: bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id), f"Knowledge Base {kb_id}")
        print(f"  ✅ Deleted Knowledge Base {kb_id}")

    s3vectors = boto3.client("s3vectors", region_name=REGION)
    try:
        s3vectors.delete_index(vectorBucketName=names["vector_bucket"], indexName=names["vector_index"])
        print(f"  ✅ Deleted vector index {names['vector_index']}")
    except s3vectors.exceptions.NotFoundException:
        pass
    try:
        s3vectors.delete_vector_bucket(vectorBucketName=names["vector_bucket"])
        print(f"  ✅ Deleted vector bucket {names['vector_bucket']}")
    except s3vectors.exceptions.NotFoundException:
        print(f"  ℹ️ Vector bucket {names['vector_bucket']} not found")

    s3 = boto3.resource("s3", region_name=REGION)
    bucket = s3.Bucket(names["docs_bucket"])
    try:
        bucket.objects.all().delete()
        bucket.delete()
        print(f"  ✅ Deleted S3 bucket {names['docs_bucket']}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchBucket":
            raise
        print(f"  ℹ️ S3 bucket {names['docs_bucket']} not found")

    _delete_role(names["role"])


# ---------------------------------------------------------------------------
# Optional Observability lab, SSM parameters and local files
# ---------------------------------------------------------------------------


def delete_observability_logs() -> None:
    _delete_log_groups(OBSERVABILITY_LOG_GROUP)


def delete_ssm_parameters() -> None:
    ssm = boto3.client("ssm", region_name=REGION)
    names = []
    for page in ssm.get_paginator("get_parameters_by_path").paginate(Path=SSM_PREFIX, Recursive=True):
        names.extend(p["Name"] for p in page["Parameters"])
    for i in range(0, len(names), 10):
        ssm.delete_parameters(Names=names[i : i + 10])
    print(f"  ✅ Deleted {len(names)} SSM parameters under {SSM_PREFIX}")


def delete_local_files() -> None:
    for file in LOCAL_FILES:
        path = Path(file)
        if path.exists():
            path.unlink()
            print(f"  ✅ Deleted {file}")
