import base64
import hashlib
import hmac
import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Dict

import boto3
import yaml
from boto3.session import Session

sts_client = boto3.client("sts")

# Get AWS account details
REGION = boto3.session.Session().region_name

username = "testuser"
sm_name = "customer_support_agent"


role_name = f"CustomerSupportAssistantBedrockAgentCoreRole-{REGION}"
policy_name = f"CustomerSupportAssistantBedrockAgentCorePolicy-{REGION}"

# Lab 1: Amazon Bedrock Knowledge Base used by the technical support tool
KB_DOCS_DIR = Path(__file__).parent / "lab1_knowledge_base"
KB_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
KB_EMBEDDING_DIMENSIONS = 1024

# Lab 3: AgentCore Gateway tools (AWS Lambda) and IAM roles
GATEWAY_LAMBDA_NAME = "customersupport-gateway-tools"
GATEWAY_LAMBDA_ROLE_NAME = f"CustomerSupportGatewayLambdaRole-{REGION}"
GATEWAY_ROLE_NAME = f"CustomerSupportGatewayRole-{REGION}"
GATEWAY_LAMBDA_SOURCE = Path(__file__).parent / "lab3_gateway" / "lambda_function.py"
GATEWAY_TOOL_SCHEMA = Path(__file__).parent / "lab3_gateway" / "tool_schema.json"


def get_ssm_parameter(name: str, with_decryption: bool = True) -> str:
    ssm = boto3.client("ssm")

    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)

    return response["Parameter"]["Value"]


def put_ssm_parameter(name: str, value: str, parameter_type: str = "String", with_encryption: bool = False) -> None:
    ssm = boto3.client("ssm")

    put_params = {
        "Name": name,
        "Value": value,
        "Type": parameter_type,
        "Overwrite": True,
    }

    if with_encryption:
        put_params["Type"] = "SecureString"

    ssm.put_parameter(**put_params)


def delete_ssm_parameter(name: str) -> None:
    ssm = boto3.client("ssm")
    try:
        ssm.delete_parameter(Name=name)
    except ssm.exceptions.ParameterNotFound:
        pass


def load_api_spec(file_path: str) -> list:
    with open(file_path, "r") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Expected a list in the JSON file")
    return data


def get_aws_region() -> str:
    session = Session()
    return session.region_name


def get_aws_account_id() -> str:
    sts = boto3.client("sts")
    return sts.get_caller_identity()["Account"]


def get_cognito_client_secret() -> str:
    client = boto3.client("cognito-idp")
    response = client.describe_user_pool_client(
        UserPoolId=get_ssm_parameter("/app/customersupport/agentcore/pool_id"),
        ClientId=get_ssm_parameter("/app/customersupport/agentcore/client_id"),
    )
    return response["UserPoolClient"]["ClientSecret"]


def read_config(file_path: str) -> Dict[str, Any]:
    """
    Read configuration from a file path. Supports JSON, YAML, and YML formats.

    Args:
        file_path (str): Path to the configuration file

    Returns:
        Dict[str, Any]: Configuration data as a dictionary

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file format is not supported or invalid
        yaml.YAMLError: If YAML parsing fails
        json.JSONDecodeError: If JSON parsing fails
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    # Get file extension to determine format
    _, ext = os.path.splitext(file_path.lower())

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            if ext == ".json":
                return json.load(file)
            elif ext in [".yaml", ".yml"]:
                return yaml.safe_load(file)
            else:
                # Try to auto-detect format by attempting JSON first, then YAML
                content = file.read()
                file.seek(0)

                # Try JSON first
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # Try YAML
                    try:
                        return yaml.safe_load(content)
                    except yaml.YAMLError:
                        raise ValueError(
                            f"Unsupported configuration file format: {ext}. Supported formats: .json, .yaml, .yml"
                        )

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in configuration file {file_path}: {e}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in configuration file {file_path}: {e}")
    except Exception as e:
        raise ValueError(f"Error reading configuration file {file_path}: {e}")


def save_customer_support_secret(secret_value):
    """Save a secret in AWS Secrets Manager."""
    boto_session = Session()
    region = boto_session.region_name
    secrets_client = boto3.client("secretsmanager", region_name=region)

    try:
        secrets_client.create_secret(
            Name=sm_name,
            SecretString=secret_value,
            Description="Secret containing the Cognito Configuration for the Customer Support Agent",
        )
        print("✅ Created secret")
    except secrets_client.exceptions.ResourceExistsException:
        secrets_client.update_secret(SecretId=sm_name, SecretString=secret_value)
        print("✅ Updated existing secret")
    except Exception as e:
        print(f"❌ Error saving secret: {str(e)}")
        return False
    return True


def get_customer_support_secret():
    """Get a secret value from AWS Secrets Manager."""
    boto_session = Session()
    region = boto_session.region_name
    secrets_client = boto3.client("secretsmanager", region_name=region)
    try:
        response = secrets_client.get_secret_value(SecretId=sm_name)
        return response["SecretString"]
    except Exception as e:
        print(f"Error getting secret: {str(e)}")
        return None


def delete_customer_support_secret():
    """Delete a secret from AWS Secrets Manager."""
    boto_session = Session()
    region = boto_session.region_name
    secrets_client = boto3.client("secretsmanager", region_name=region)
    try:
        secrets_client.delete_secret(SecretId=sm_name, ForceDeleteWithoutRecovery=True)
        print("✅ Deleted secret!")
        return True
    except Exception as e:
        print(f"❌ Error deleting secret: {str(e)}")
        return False


def get_or_create_cognito_pool(refresh_token=False):
    boto_session = Session()
    region = boto_session.region_name
    # Initialize Cognito client
    cognito_client = boto3.client("cognito-idp", region_name=region)
    try:
        # check for existing cognito pool
        cognito_config_str = get_customer_support_secret()
        cognito_config = json.loads(cognito_config_str)
        if refresh_token:
            cognito_config["bearer_token"] = reauthenticate_user(
                cognito_config["client_id"], cognito_config["client_secret"]
            )
        return cognito_config
    except Exception:
        print("No existing cognito config found. Creating a new one..")

    try:
        # Create User Pool
        user_pool_response = cognito_client.create_user_pool(
            PoolName="customersupport-user-pool", Policies={"PasswordPolicy": {"MinimumLength": 8}}
        )
        pool_id = user_pool_response["UserPool"]["Id"]
        # Create App Client
        app_client_response = cognito_client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName="customersupport-client",
            GenerateSecret=True,
            ExplicitAuthFlows=[
                "ALLOW_USER_PASSWORD_AUTH",
                "ALLOW_REFRESH_TOKEN_AUTH",
                "ALLOW_USER_SRP_AUTH",
            ],
        )
        print(app_client_response["UserPoolClient"])
        client_id = app_client_response["UserPoolClient"]["ClientId"]
        client_secret = app_client_response["UserPoolClient"]["ClientSecret"]

        # Create User
        cognito_client.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            TemporaryPassword="Temp123!",  # pragma: allowlist secret
            MessageAction="SUPPRESS",
        )

        # Set Permanent Password
        cognito_client.admin_set_user_password(
            UserPoolId=pool_id,
            Username=username,
            Password="MyPassword123!",  # pragma: allowlist secret
            Permanent=True,
        )

        message = bytes(username + client_id, "utf-8")
        key = bytes(client_secret, "utf-8")
        secret_hash = base64.b64encode(hmac.new(key, message, digestmod=hashlib.sha256).digest()).decode()

        # Authenticate User and get Access Token
        auth_response = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": "MyPassword123!",  # pragma: allowlist secret
                "SECRET_HASH": secret_hash,
            },
        )
        bearer_token = auth_response["AuthenticationResult"]["AccessToken"]
        discovery_url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
        # Output the required values
        print(f"Pool id: {pool_id}")
        print(f"Discovery URL: {discovery_url}")
        print(f"Client ID: {client_id}")
        print(f"Bearer Token: {bearer_token}")
        # Return values if needed for further processing
        cognito_config = {
            "pool_id": pool_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "secret_hash": secret_hash,
            "bearer_token": bearer_token,
            "discovery_url": discovery_url,
        }
        put_ssm_parameter("/app/customersupport/agentcore/client_id", client_id)
        put_ssm_parameter("/app/customersupport/agentcore/pool_id", pool_id)
        put_ssm_parameter("/app/customersupport/agentcore/cognito_discovery_url", discovery_url)

        save_customer_support_secret(json.dumps(cognito_config))

        return cognito_config
    except Exception as e:
        print(f"Error: {e}")
        return None


def cleanup_cognito_resources(pool_id):
    """
    Delete Cognito resources including users, app clients, and user pool
    """
    try:
        # Initialize Cognito client using the same session configuration
        boto_session = Session()
        region = boto_session.region_name
        cognito_client = boto3.client("cognito-idp", region_name=region)

        if pool_id:
            try:
                # List and delete all app clients
                clients_response = cognito_client.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)

                for client in clients_response["UserPoolClients"]:
                    print(f"Deleting app client: {client['ClientName']}")
                    cognito_client.delete_user_pool_client(UserPoolId=pool_id, ClientId=client["ClientId"])

                # List and delete all users
                users_response = cognito_client.list_users(UserPoolId=pool_id, AttributesToGet=["email"])

                for user in users_response.get("Users", []):
                    print(f"Deleting user: {user['Username']}")
                    cognito_client.admin_delete_user(UserPoolId=pool_id, Username=user["Username"])

                # Delete the user pool
                print(f"Deleting user pool: {pool_id}")
                cognito_client.delete_user_pool(UserPoolId=pool_id)

                print("Successfully cleaned up all Cognito resources")
                return True

            except cognito_client.exceptions.ResourceNotFoundException:
                print(f"User pool {pool_id} not found. It may have already been deleted.")
                return True

            except Exception as e:
                print(f"Error during cleanup: {str(e)}")
                return False
        else:
            print("No matching user pool found")
            return True

    except Exception as e:
        print(f"Error initializing cleanup: {str(e)}")
        return False


def reauthenticate_user(client_id, client_secret):
    boto_session = Session()
    region = boto_session.region_name
    # Initialize Cognito client
    cognito_client = boto3.client("cognito-idp", region_name=region)
    # Authenticate User and get Access Token

    message = bytes(username + client_id, "utf-8")
    key = bytes(client_secret, "utf-8")
    secret_hash = base64.b64encode(hmac.new(key, message, digestmod=hashlib.sha256).digest()).decode()

    auth_response = cognito_client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": "MyPassword123!",  # pragma: allowlist secret
            "SECRET_HASH": secret_hash,
        },
    )
    bearer_token = auth_response["AuthenticationResult"]["AccessToken"]
    return bearer_token


def create_agentcore_runtime_execution_role():
    iam = boto3.client("iam")
    boto_session = Session()
    region = boto_session.region_name
    account_id = get_aws_account_id()

    # Trust relationship policy
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account_id}:*"},
                },
            }
        ],
    }

    # IAM policy document
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ECRImageAccess",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": [f"arn:aws:ecr:{region}:{account_id}:repository/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                "Resource": [f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogGroups"],
                "Resource": [f"arn:aws:logs:{region}:{account_id}:log-group:*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ],
            },
            {
                "Sid": "ECRTokenAccess",
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                "Resource": ["*"],
            },
            {
                "Effect": "Allow",
                "Resource": "*",
                "Action": "cloudwatch:PutMetricData",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
            {
                "Sid": "GetAgentAccessToken",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/customer_support_agent-*",
                ],
            },
            {
                "Sid": "BedrockModelInvocation",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ApplyGuardrail",
                    "bedrock:Retrieve",
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:{region}:{account_id}:*",
                ],
            },
            {
                "Sid": "AllowAgentToUseMemory",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:GetMemoryRecord",
                    "bedrock-agentcore:GetMemory",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:ListMemoryRecords",
                ],
                "Resource": [f"arn:aws:bedrock-agentcore:{region}:{account_id}:*"],
            },
            {
                "Sid": "GetMemoryId",
                "Effect": "Allow",
                "Action": ["ssm:GetParameter"],
                "Resource": [f"arn:aws:ssm:{region}:{account_id}:parameter/*"],
            },
            {
                "Sid": "GatewayAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetGateway",
                    "bedrock-agentcore:InvokeGateway",
                ],
                "Resource": [f"arn:aws:bedrock-agentcore:{region}:{account_id}:gateway/*"],
            },
        ],
    }

    try:
        # Check if role already exists
        try:
            existing_role = iam.get_role(RoleName=role_name)
            print(f"ℹ️ Role {role_name} already exists")
            print(f"Role ARN: {existing_role['Role']['Arn']}")
            return existing_role["Role"]["Arn"]
        except iam.exceptions.NoSuchEntityException:
            pass

        # Create IAM role
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="IAM role for Amazon Bedrock AgentCore with required permissions",
        )

        print(f"✅ Created IAM role: {role_name}")
        print(f"Role ARN: {role_response['Role']['Arn']}")

        # Check if policy already exists
        policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

        try:
            iam.get_policy(PolicyArn=policy_arn)
            print(f"ℹ️ Policy {policy_name} already exists")
        except iam.exceptions.NoSuchEntityException:
            # Create policy
            policy_response = iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document),
                Description="Policy for Amazon Bedrock AgentCore permissions",
            )
            print(f"✅ Created policy: {policy_name}")
            policy_arn = policy_response["Policy"]["Arn"]

        # Attach policy to role
        try:
            iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
            print("✅ Attached policy to role")
        except Exception as e:
            if "already attached" in str(e).lower():
                print("ℹ️ Policy already attached to role")
            else:
                raise

        print(f"Policy ARN: {policy_arn}")

        put_ssm_parameter(
            "/app/customersupport/agentcore/runtime_execution_role_arn",
            role_response["Role"]["Arn"],
        )
        return role_response["Role"]["Arn"]

    except Exception as e:
        print(f"❌ Error creating IAM role: {str(e)}")
        return None


def delete_agentcore_runtime_execution_role():
    iam = boto3.client("iam")

    try:
        account_id = boto3.client("sts").get_caller_identity()["Account"]
        policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"

        # Detach policy from role
        try:
            iam.detach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
            print("✅ Detached policy from role")
        except Exception:
            pass

        # Delete role
        try:
            iam.delete_role(RoleName=role_name)
            print(f"✅ Deleted role: {role_name}")
        except Exception:
            pass

        # Delete policy
        try:
            iam.delete_policy(PolicyArn=policy_arn)
            print(f"✅ Deleted policy: {policy_name}")
        except Exception:
            pass

        delete_ssm_parameter("/app/customersupport/agentcore/runtime_execution_role_arn")

    except Exception as e:
        print(f"❌ Error during cleanup: {str(e)}")


# ---------------------------------------------------------------------------
# Lab 3: AWS resources for AgentCore Gateway
# ---------------------------------------------------------------------------


def _get_or_create_role(role_name: str, trust_policy: dict, description: str) -> tuple[str, bool]:
    """Return (role ARN, created) for an IAM role, creating it if it doesn't exist."""
    iam = boto3.client("iam")
    try:
        return iam.get_role(RoleName=role_name)["Role"]["Arn"], False
    except iam.exceptions.NoSuchEntityException:
        pass
    role = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description=description,
    )
    print(f"✅ Created IAM role: {role_name}")
    return role["Role"]["Arn"], True


def create_gateway_tools_lambda() -> str:
    """Create (or update) the Lambda function that implements the Gateway tools.

    The function code is the single file lab_helpers/lab3_gateway/lambda_function.py,
    zipped in memory. Returns the function ARN, also stored in SSM.
    """
    iam = boto3.client("iam")
    lambda_client = boto3.client("lambda", region_name=REGION)

    role_arn, _ = _get_or_create_role(
        GATEWAY_LAMBDA_ROLE_NAME,
        {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}
            ],
        },
        "Execution role for the customer support Gateway tools Lambda",
    )
    iam.attach_role_policy(
        RoleName=GATEWAY_LAMBDA_ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(GATEWAY_LAMBDA_SOURCE, arcname="lambda_function.py")
    code = buffer.getvalue()

    try:
        function = lambda_client.get_function(FunctionName=GATEWAY_LAMBDA_NAME)["Configuration"]
        lambda_client.update_function_code(FunctionName=GATEWAY_LAMBDA_NAME, ZipFile=code)
        print(f"ℹ️ Lambda function {GATEWAY_LAMBDA_NAME} already exists: code updated")
    except lambda_client.exceptions.ResourceNotFoundException:
        # A newly created IAM role can take a few seconds before Lambda is able to assume it
        for attempt in range(10):
            try:
                function = lambda_client.create_function(
                    FunctionName=GATEWAY_LAMBDA_NAME,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler="lambda_function.lambda_handler",
                    Code={"ZipFile": code},
                    Description="Mocked customer support tools exposed through AgentCore Gateway",
                    Timeout=10,
                )
                break
            except lambda_client.exceptions.InvalidParameterValueException as e:
                if "cannot be assumed" not in str(e) or attempt == 9:
                    raise
                print("⏳ Waiting for the IAM role to propagate...")
                time.sleep(5)
        print(f"✅ Created Lambda function: {GATEWAY_LAMBDA_NAME}")

    lambda_client.get_waiter("function_active_v2").wait(FunctionName=GATEWAY_LAMBDA_NAME)
    lambda_client.get_waiter("function_updated_v2").wait(FunctionName=GATEWAY_LAMBDA_NAME)
    function_arn = function["FunctionArn"]
    put_ssm_parameter("/app/customersupport/agentcore/lambda_arn", function_arn)
    return function_arn


def create_gateway_role(lambda_arn: str) -> str:
    """Create (or reuse) the IAM role AgentCore Gateway assumes to invoke the tools Lambda."""
    iam = boto3.client("iam")
    account_id = get_aws_account_id()

    role_arn, created = _get_or_create_role(
        GATEWAY_ROLE_NAME,
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {"aws:SourceAccount": account_id},
                        "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:*"},
                    },
                }
            ],
        },
        "Role assumed by AgentCore Gateway to invoke the customer support tools",
    )
    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="InvokeGatewayToolsLambda",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": lambda_arn}],
            }
        ),
    )
    if created:
        print("⏳ Waiting 10 seconds for the new IAM role to propagate...")
        time.sleep(10)

    put_ssm_parameter("/app/customersupport/agentcore/gateway_iam_role", role_arn)
    return role_arn


# ---------------------------------------------------------------------------
# Optional Identity lab: Cognito domain for the OAuth2 endpoints
# ---------------------------------------------------------------------------


def get_or_create_cognito_domain(pool_id: str) -> str:
    """Return the Cognito domain prefix of the user pool, creating one if needed."""
    cognito = boto3.client("cognito-idp", region_name=REGION)
    domain = cognito.describe_user_pool(UserPoolId=pool_id)["UserPool"].get("Domain")
    if domain:
        return domain

    domain = f"customersupport-{get_aws_account_id()}-{REGION}"
    cognito.create_user_pool_domain(Domain=domain, UserPoolId=pool_id)
    print(f"✅ Created Cognito domain: {domain}")
    return domain


# ---------------------------------------------------------------------------
# Lab 1: names of the Knowledge Base resources (shared with the Lab 7 cleanup)
# ---------------------------------------------------------------------------


def get_kb_resource_names() -> Dict[str, str]:
    """Names of the AWS resources backing the Lab 1 Knowledge Base.

    S3 bucket names are global, so they include the account ID and region.
    """
    account_id = get_aws_account_id()
    return {
        "docs_bucket": f"customersupport-kb-docs-{account_id}-{REGION}",
        "vector_bucket": f"customersupport-kb-vectors-{account_id}-{REGION}",
        "vector_index": "customersupport-kb-index",
        "role": f"CustomerSupportKnowledgeBaseRole-{REGION}",
        "knowledge_base": "customersupport-kb",
        "data_source": "customersupport-kb-docs",
    }
