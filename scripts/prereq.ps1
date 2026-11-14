#!/usr/bin/env pwsh

# Enable strict error handling
$ErrorActionPreference = "Stop"

# ----- Config -----
$BucketName = "customersupport112"
$InfraStackName = "CustomerSupportStackInfra"
$CognitoStackName = "CustomerSupportStackCognito"

$InfraTemplateFile = "prerequisite/infrastructure.yaml"
$CognitoTemplateFile = "prerequisite/cognito.yaml"

try {
    $Region = aws configure get region 2>$null
    if (-not $Region) { $Region = "us-west-2" }
} catch {
    $Region = "us-west-2"
}

# Get AWS Account ID with proper error handling
Write-Host "Getting AWS Account ID..." -ForegroundColor Cyan
try {
    $AccountId = aws sts get-caller-identity --query Account --output text 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $AccountId -or $AccountId -eq "None") {
        throw "Failed to get AWS Account ID"
    }
} catch {
    Write-Host "Failed to get AWS Account ID. Please check your AWS credentials and network connectivity." -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}

$FullBucketName = "$BucketName-$AccountId-$Region"
$ZipFile = "lambda.zip"
$LayerZipFile = "ddgs-layer.zip"
$LayerRequirements = "prerequisite/lambda/layer-requirements.txt"
$LayerBuildDir = "build/ddgs-layer"
$S3LayerKey = $LayerZipFile
$LambdaSrc = "prerequisite/lambda/python"
$S3Key = $ZipFile

Write-Host "Region: $Region" -ForegroundColor Green
Write-Host "Account ID: $AccountId" -ForegroundColor Green

# ----- 1. Create S3 bucket -----
Write-Host "Using S3 bucket: $FullBucketName" -ForegroundColor Cyan
try {
    if ($Region -eq "us-east-1") {
        aws s3api create-bucket --bucket $FullBucketName 2>$null
    } else {
        aws s3api create-bucket --bucket $FullBucketName --region $Region --create-bucket-configuration LocationConstraint=$Region 2>$null
    }
} catch {
    Write-Host "Bucket may already exist or be owned by you." -ForegroundColor Yellow
}

# ----- 2. Zip Lambda code -----
Write-Host "Zipping contents of $LambdaSrc into $ZipFile..." -ForegroundColor Cyan
try {
    $LambdaFiles = Get-ChildItem -Path $LambdaSrc -Exclude "*.zip", "__pycache__"
    Compress-Archive -Path $LambdaFiles.FullName -DestinationPath $ZipFile -Force
} catch {
    Write-Host "Failed to create zip file. Ensure you have PowerShell 5.0+ or install 7-Zip." -ForegroundColor Red
    exit 1
}

# ----- 2b. Build the DDGS Lambda layer (Linux x86_64, Python 3.12) -----
Write-Host "Building Lambda layer $LayerZipFile from $LayerRequirements..." -ForegroundColor Cyan
if (Test-Path $LayerBuildDir) { Remove-Item -Recurse -Force $LayerBuildDir }
New-Item -ItemType Directory -Force -Path "$LayerBuildDir/python" | Out-Null
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Red
    exit 1
}
uv pip install --quiet --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all: --target "$LayerBuildDir/python" -r $LayerRequirements
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to build the Lambda layer." -ForegroundColor Red
    exit 1
}
Compress-Archive -Path "$LayerBuildDir/python" -DestinationPath $LayerZipFile -Force

# ----- 3. Upload to S3 -----
Write-Host "Uploading $ZipFile to s3://$FullBucketName/$S3Key..." -ForegroundColor Cyan
aws s3 cp $ZipFile "s3://$FullBucketName/$S3Key"

Write-Host "Uploading $LayerZipFile to s3://$FullBucketName/$S3LayerKey..." -ForegroundColor Cyan
aws s3 cp $LayerZipFile "s3://$FullBucketName/$S3LayerKey"

# ----- 4. Deploy CloudFormation -----
function Deploy-Stack {
    param(
        [string]$StackName,
        [string]$TemplateFile,
        [string[]]$Parameters
    )
    
    Write-Host "Deploying CloudFormation stack: $StackName" -ForegroundColor Cyan
    
    $deployArgs = @(
        "cloudformation", "deploy",
        "--stack-name", $StackName,
        "--template-file", $TemplateFile,
        "--s3-bucket", $FullBucketName,
        "--capabilities", "CAPABILITY_NAMED_IAM",
        "--region", $Region
    )
    
    if ($Parameters) {
        $deployArgs += "--parameter-overrides"
        $deployArgs += $Parameters
    }
    
    $output = & aws @deployArgs 2>&1
    Write-Host "AWS CLI Exit Code: $LASTEXITCODE" -ForegroundColor Yellow
    Write-Host "AWS CLI Output: $output" -ForegroundColor Yellow
    
    if ($LASTEXITCODE -ne 0) {
        if ($output -match "No changes to deploy") {
            Write-Host "No updates for stack $StackName, continuing..." -ForegroundColor Yellow
            return $true
        } else {
            Write-Host "Error deploying stack ${StackName}:" -ForegroundColor Red
            Write-Host $output -ForegroundColor Red
            return $false
        }
    } else {
        Write-Host "Stack $StackName deployed successfully." -ForegroundColor Green
        return $true
    }
}

# ----- Run both stacks -----
Write-Host "Starting deployment of infrastructure stack with LambdaS3Bucket = $FullBucketName..." -ForegroundColor Cyan
$infraParams = @("LambdaS3Bucket=$FullBucketName", "LambdaS3Key=$S3Key", "LayerS3Key=$S3LayerKey")
$infraSuccess = Deploy-Stack -StackName $InfraStackName -TemplateFile $InfraTemplateFile -Parameters $infraParams

Write-Host "Starting deployment of Cognito stack..." -ForegroundColor Cyan
$cognitoParams = @("UserPoolName=CustomerSupportGatewayPool", "MachineAppClientName=CustomerSupportMachineClient", "WebAppClientName=CustomerSupportWebClient")
$cognitoSuccess = Deploy-Stack -StackName $CognitoStackName -TemplateFile $CognitoTemplateFile -Parameters $cognitoParams

if ($infraSuccess -and $cognitoSuccess) {
    Write-Host "Deployment complete." -ForegroundColor Green
} else {
    Write-Host "Deployment failed." -ForegroundColor Red
    exit 1
}
