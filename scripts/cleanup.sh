#!/bin/bash

set -e
set -o pipefail

# ----- Config -----
# Defaults must match scripts/prereq.sh
BUCKET_NAME=${1:-customersupport112}
INFRA_STACK_NAME=${2:-CustomerSupportStackInfra}
COGNITO_STACK_NAME=${3:-CustomerSupportStackCognito}
REGION=${AWS_REGION:-$(aws configure get region 2>/dev/null || echo "us-west-2")}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>&1) || ACCOUNT_ID=""
FULL_BUCKET_NAME="${BUCKET_NAME}-${ACCOUNT_ID}-${REGION}"
ZIP_FILE="lambda.zip"
LAYER_ZIP_FILE="ddgs-layer.zip"
LAYER_BUILD_DIR="build"

if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "None" ]; then
    echo "❌ Failed to get AWS Account ID. Please check your AWS credentials and network connectivity."
    echo "Error: $ACCOUNT_ID"
    exit 1
fi

# ----- Confirm Deletion -----
read -p "⚠️ Are you sure you want to delete stacks '$INFRA_STACK_NAME', '$COGNITO_STACK_NAME' and clean up S3? (y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "❌ Cleanup cancelled."
  exit 1
fi

# ----- 1. Delete CloudFormation stacks -----
echo "🧨 Deleting stack: $INFRA_STACK_NAME..."
aws cloudformation delete-stack --stack-name "$INFRA_STACK_NAME" --region "$REGION"
echo "⏳ Waiting for $INFRA_STACK_NAME to be deleted..."
aws cloudformation wait stack-delete-complete --stack-name "$INFRA_STACK_NAME" --region "$REGION"
echo "✅ Stack $INFRA_STACK_NAME deleted."

echo "🧨 Deleting stack: $COGNITO_STACK_NAME..."
aws cloudformation delete-stack --stack-name "$COGNITO_STACK_NAME" --region "$REGION"
echo "⏳ Waiting for $COGNITO_STACK_NAME to be deleted..."
aws cloudformation wait stack-delete-complete --stack-name "$COGNITO_STACK_NAME" --region "$REGION"
echo "✅ Stack $COGNITO_STACK_NAME deleted."

# ----- 2. Delete zip file from S3 -----
echo "🧹 Deleting all contents of s3://$FULL_BUCKET_NAME..."
aws s3 rm "s3://$FULL_BUCKET_NAME" --recursive || echo "⚠️ Failed to clean bucket or it is already empty."

# ----- 3. Optionally delete the bucket -----
read -p "🪣 Do you want to delete the bucket '$FULL_BUCKET_NAME'? (y/N): " delete_bucket
if [[ "$delete_bucket" == "y" || "$delete_bucket" == "Y" ]]; then
  echo "🚮 Deleting bucket $FULL_BUCKET_NAME..."
  aws s3 rb "s3://$FULL_BUCKET_NAME" --force
  echo "✅ Bucket deleted."
else
  echo "🪣 Bucket retained: $FULL_BUCKET_NAME"
fi

# ----- 4. Clean up local build artifacts -----
echo "🗑️ Removing local build artifacts ($ZIP_FILE, $LAYER_ZIP_FILE, $LAYER_BUILD_DIR/)..."
rm -f "$ZIP_FILE" "$LAYER_ZIP_FILE"
rm -rf "$LAYER_BUILD_DIR"

echo "✅ Cleanup complete."
