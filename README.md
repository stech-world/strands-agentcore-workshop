# End-to-End Customer Support Agent with AgentCore

Move a customer support agent from prototype to production using Amazon Bedrock AgentCore services. Across six labs, you'll build a complete system that handles customer conversations with memory, shared tools, access control, observability, quality evaluations, and a web interface.

The workshop is intentionally minimal: there is no infrastructure to deploy upfront. Each lab creates with boto3 only the AWS resources it needs, in a dedicated section, and the last lab deletes all of them. Most of the agent's tools are **mocked** with small in-memory datasets; the technical support tool searches a real Amazon Bedrock Knowledge Base, built step by step in Lab 1.

> [!IMPORTANT]
> This workshop is for educational purposes. It demonstrates how AgentCore services are used when migrating an agentic use case from prototype to production. It is not intended for direct use in production environments.

## Architecture Overview

By the end of the 6 labs, you will have built the following architecture:

<div style="text-align:left">
    <img src="images/architecture_lab6_streamlit.png" width="100%"/>
</div>

## Prerequisites

- You need an AWS account with access to Amazon Bedrock.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) must be installed. It manages Python and all dependencies, so you don't need a separate Python installation.
- The AWS CLI must be configured with appropriate credentials and a default region.
- Amazon Nova 2 Lite and Amazon Titan Text Embeddings V2 must be enabled in your [Amazon Bedrock model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) settings.
- Use a region where [Amazon S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-regions-quotas.html) and Amazon Bedrock AgentCore are available (for example `us-east-1` or `us-west-2`).
- [CloudWatch Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html) must be enabled to see AgentCore Observability traces (Labs 4 and 5).

## Getting Started

### Install dependencies

From the repository root, create the project environment:

```bash
uv sync
```

This creates a `.venv` folder with Python 3.12 (pinned in `.python-version`, downloaded by uv if needed) and installs the exact versions locked in `uv.lock`: the agent dependencies plus the `notebooks`, `frontend`, and `optional-labs` dependency groups. Run `uv sync` again whenever you pull changes to `pyproject.toml` or `uv.lock`.

### Configure AWS credentials for the notebooks

The notebooks, and the `aws` commands they run, use the standard AWS credential chain of the Jupyter kernel process. Credentials exported only in a terminal session (for example by `assume` from Granted) are not visible to a kernel started by VS Code.

The simplest setup is a `.env` file at the repository root (ignored by git) with your AWS profile and region:

```bash
AWS_PROFILE=<your-profile>
AWS_DEFAULT_REGION=<region>   # read by boto3
AWS_REGION=<region>           # read by the AWS CLI
```

- **VS Code** loads `.env` into the notebook kernels (`python.envFile` in `.vscode/settings.json`). Restart the kernel after changing it.
- **JupyterLab**: start it with `uv run --env-file .env jupyter lab`.

The profile must be able to obtain credentials on its own: an IAM Identity Center (SSO) profile after `aws sso login`, or a profile with `credential_process`. Granted can generate profiles with `credential_process = granted credential-process --profile <name>`, which refresh the credentials automatically.

> [!TIP]
> If `aws sts get-caller-identity` fails with `InvalidClientTokenId`, check `~/.aws/credentials` for a section with the same name as your profile: static keys there (for example left by `assume --export`) take precedence over `credential_process` and may be expired.

### Required IAM permissions

The IAM user or role behind your AWS credentials (run `aws sts get-caller-identity` to check) must be able to create and delete the resources used across the labs. On a personal sandbox account the simplest option is an identity with the `AdministratorAccess` managed policy. If you need a scoped-down policy, it must cover at least:

| Service                             | Used for                                                                           |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| Amazon Bedrock                      | Model invocation (Amazon Nova 2 Lite) and the Knowledge Base                       |
| Amazon S3 and Amazon S3 Vectors     | Knowledge Base documents and vector store                                          |
| Amazon Bedrock AgentCore            | Memory, Gateway, Identity, Policy, Runtime, and Evaluations                        |
| AWS IAM                             | Creating the roles for the Knowledge Base, the Gateway and its Lambda function, the Runtime and Evaluations |
| AWS Lambda                          | The function that implements the Gateway tools                                     |
| Amazon Cognito                      | User pool and app client for Gateway, Runtime and frontend authentication          |
| AWS Systems Manager Parameter Store | Sharing resource IDs between labs (`/app/customersupport/*`)                       |
| AWS Secrets Manager                 | Storing the Cognito client configuration                                           |
| Amazon ECR and AWS CodeBuild        | Building and storing the AgentCore Runtime container image (starter toolkit)      |
| Amazon CloudWatch and AWS X-Ray     | Logs, traces, and Transaction Search for observability                             |

### Open the notebooks and start Lab 1

Run the notebooks on the project environment, using one of these options:

- **JupyterLab**: run `uv run jupyter lab` from the repository root.
- **VS Code**: open the folder and select the `.venv` interpreter as the notebook kernel. The workspace settings in `.vscode/settings.json` already point to it.
- **An existing Jupyter server (for example SageMaker Studio)**: install uv there, run `uv sync`, register the environment as a kernel with `uv run python -m ipykernel install --user --name strands-agentcore-workshop`, and select that kernel in each notebook.

Then open [Lab 1](lab-01-create-an-agent.ipynb) and follow along. Each lab builds on the previous one. The notebooks never install packages themselves: the first cells only check that they are running on the uv environment, and command-line tools (Streamlit, OpenTelemetry instrumentation) are launched through `uv run`.

## Labs

| Lab | Title                                                                | Notebook                                   | Time    | What You'll Learn                                         |
| --- | -------------------------------------------------------------------- | ------------------------------------------ | ------- | --------------------------------------------------------- |
| 1   | [Create Agent Prototype](#lab-1-create-agent-prototype)              | [Notebook](lab-01-create-an-agent.ipynb)   | ~25 min | Agent creation with Strands Agents, tools and a Knowledge Base |
| 2   | [Add Memory](#lab-2-add-memory)                                      | [Notebook](lab-02-agentcore-memory.ipynb)  | ~20 min | AgentCore Memory for short-term and long-term persistence |
| 3   | [Scale with Gateway & Identity](#lab-3-scale-with-gateway--identity) | [Notebook](lab-03-agentcore-gateway.ipynb) | ~30 min | AgentCore Gateway, Identity and Policy for secure tool sharing |
| 4   | [Deploy to Production](#lab-4-deploy-to-production)                  | [Notebook](lab-04-agentcore-runtime.ipynb) | ~30 min | AgentCore Runtime with production-grade Observability     |
| 5   | [Evaluate Agent Performance](#lab-5-evaluate-agent-performance)      | [Notebook](lab-05-agentcore-evals.ipynb)   | ~10 min | AgentCore Evaluations for quality monitoring              |
| 6   | [Build User Interface](#lab-6-build-user-interface)                  | [Notebook](lab-06-frontend.ipynb)          | ~20 min | Frontend integration with secure agent endpoints          |
| 7   | [Cleanup](#cleanup)                                                  | [Notebook](lab-07-cleanup.ipynb)           | ~10 min | Deleting every resource created by the workshop           |

### Lab 1: Create Agent Prototype

Build a customer support agent prototype using Strands Agents and Amazon Nova 2 Lite with four tools:

- Look up return policies for different product categories (mocked).
- Get product information and specifications (mocked).
- Search the web for updated information (mocked).
- Search the technical documentation in an Amazon Bedrock Knowledge Base. You create every resource behind it with boto3: S3 bucket with the documents, S3 Vectors bucket and index, IAM role, Knowledge Base, data source and ingestion job.

### Lab 2: Add Memory

Transform your "goldfish agent" into one that remembers customers across conversations using AgentCore Memory:

- Store conversation history persistently with short-term memory.
- Extract customer preferences and behavioral patterns with long-term memory.
- Maintain context awareness across multiple sessions so the agent can personalize responses.

### Lab 3: Scale with Gateway & Identity

Move from local tools to shared services using AgentCore Gateway and AgentCore Identity:

- Expose a Lambda function (warranty check and web search) as MCP-compatible tools through AgentCore Gateway.
- Secure your gateway endpoint with JWT-based authentication using Amazon Cognito.
- (Optional) Define fine-grained access control with Cedar policies using AgentCore Policy to restrict specific tool invocations.

### Lab 4: Deploy to Production

Deploy your agent to AgentCore Runtime to handle real traffic with full observability:

- Deploy your agent to a fully managed, serverless runtime with minimal code changes (only four lines added).
- Enable session continuity and session isolation so each customer gets a separate conversation context.
- Monitor agent behavior through CloudWatch GenAI Observability with automatic tracing and metrics.

### Lab 5: Evaluate Agent Performance

Set up continuous quality monitoring for your production agent using AgentCore Evaluations:

- Configure online evaluation with built-in evaluators for goal success rate, correctness, and tool selection accuracy.
- Generate test interactions and review evaluation results through AgentCore Observability dashboards.
- Use quality metrics to identify areas for improvement and maintain high agent performance.

### Lab 6: Build User Interface

Create a Streamlit web app that customers can use to interact with your deployed agent:

- Provide a chat interface with real-time response streaming powered by AgentCore Runtime.
- Implement secure user authentication through Amazon Cognito.
- Manage user sessions with persistent conversation history via AgentCore Memory.

## Optional Labs

- [Identity Deep Dive](Optional-lab-identity.ipynb) -- Integrate Google Calendar via AgentCore Identity using OAuth2 3LO flows, enabling your agent to create events and retrieve calendars on behalf of authenticated users.
- [Observability Deep Dive](Optional-lab-agentcore-observability.ipynb) -- Set up AgentCore Observability for agents running outside of AgentCore Runtime using AWS OpenTelemetry Python instrumentation and CloudWatch GenAI Observability.

## AWS Resources by Lab

There is nothing to deploy before Lab 1. Each lab creates the resources it needs with boto3 or the AgentCore starter toolkit (re-running a lab reuses the existing ones), and stores their IDs in SSM Parameter Store under `/app/customersupport/` so that the next labs can find them:

| Lab                        | Resources created                                                                                                     |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 1                          | Knowledge Base `customersupport-kb` with its S3 data source, documents S3 bucket, S3 Vectors bucket and index, IAM role |
| 2                          | AgentCore Memory `CustomerSupportMemory`                                                                              |
| 3                          | Cognito user pool `customersupport-user-pool` with app client and test user, Secrets Manager secret, Lambda function `customersupport-gateway-tools` and its role, Gateway IAM role, AgentCore Gateway `customersupport-gw` and target, Policy Engine `customersupport_pe` and policies |
| 4                          | AgentCore Runtime `customer_support_agent` and its execution role, ECR repository, CodeBuild project                  |
| 5                          | Online evaluation configuration `customer_support_agent_eval` and its execution role                                  |
| 6                          | None: reuses the Cognito user pool from Lab 3 and the Runtime from Lab 4                                              |
| Identity Deep Dive         | AgentCore Identity OAuth2 credential providers, Cognito domain                                                        |
| Observability Deep Dive    | CloudWatch log group `agents/customer-support-assistant-logs`                                                         |

Lab 1 creates the Knowledge Base resources directly in the notebook cells; the helpers used by the other labs are in [lab_helpers/utils.py](lab_helpers/utils.py). To list the IDs stored so far, run `bash scripts/list_ssm_parameters.sh`.

## Repository Structure

| Path                                    | Content                                                                    |
| --------------------------------------- | -------------------------------------------------------------------------- |
| `lab-0*.ipynb`, `Optional-lab-*.ipynb`  | The lab notebooks                                                          |
| `lab_helpers/lab1_strands_agent.py`     | Model, system prompt and local tools, reused by Labs 2-4                   |
| `lab_helpers/lab1_knowledge_base/`      | Technical documentation ingested into the Lab 1 Knowledge Base             |
| `lab_helpers/lab2_memory.py`            | AgentCore Memory resource and hooks                                        |
| `lab_helpers/lab3_gateway/`             | Lambda function and tool schema exposed through AgentCore Gateway          |
| `lab_helpers/lab4_runtime.py`           | Agent entrypoint deployed to AgentCore Runtime (written by Lab 4)          |
| `lab_helpers/lab6_frontend/`            | Streamlit customer frontend                                                |
| `lab_helpers/utils.py`                  | Helpers to create the AWS resources used by the labs                       |
| `lab_helpers/cleanup.py`                | Helpers to delete them, used by Lab 7                                      |

## Managing Dependencies

All Python dependencies are managed with uv:

| File               | Purpose                                                                                                         |
| ------------------ | --------------------------------------------------------------------------------------------------------------- |
| `pyproject.toml`   | Declares the agent dependencies and the `notebooks`, `frontend`, and `optional-labs` dependency groups           |
| `uv.lock`          | Exact, cross-platform versions of every package. Commit it together with any change to `pyproject.toml`         |
| `.python-version`  | Python version uv uses for the local environment                                                                |
| `requirements.txt` | Generated from `uv.lock`, agent dependencies only. AgentCore Runtime builds the container from it in Lab 4. Don't edit it by hand |

To add or update a dependency:

```bash
uv add <package>                     # agent dependency (also shipped to AgentCore Runtime)
uv add --group frontend <package>    # or --group notebooks / --group optional-labs
uv lock --upgrade-package <package>  # upgrade a single locked package
```

After changing the agent dependencies, regenerate `requirements.txt` (Lab 4 also does this right before configuring the Runtime):

```bash
uv export --no-default-groups --no-hashes --no-emit-project --no-header --no-annotate --format requirements-txt -o requirements.txt
```

## Cleanup

When you're done, run the [Cleanup notebook](lab-07-cleanup.ipynb) from the repository root. It deletes every resource listed in [AWS Resources by Lab](#aws-resources-by-lab), in reverse order of creation, together with the SSM parameters and the files generated locally.

The cleanup only deletes resources created by this workshop (found by name or by the IDs saved in SSM) and skips the ones that don't exist, so you can run it even if you skipped some labs, and run it again if a step failed.
