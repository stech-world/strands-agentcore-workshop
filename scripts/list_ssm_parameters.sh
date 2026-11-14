#!/bin/bash

set -e
set -o pipefail

NAMESPACE="/app/customersupport"
REGION=${AWS_REGION:-$(aws configure get region 2>/dev/null || echo "us-west-2")}

echo "🔍 Listing SSM parameters under namespace: $NAMESPACE/*"
echo "📍 Region: $REGION"
echo ""

# Fetch and paginate through all parameters under the given path
aws ssm get-parameters-by-path \
  --path "$NAMESPACE" \
  --recursive \
  --with-decryption \
  --region "$REGION" \
  --query "Parameters[*].{Name:Name,Value:Value}" \
  --output table
