#!/bin/bash
# LocalStack init script — runs automatically when LocalStack is ready
# Creates the S3 bucket used for PIR PDF reports

echo "Initializing LocalStack AWS resources..."

awslocal s3 mb s3://novaops-pir-reports --region us-east-1
echo "Created S3 bucket: novaops-pir-reports"

echo "LocalStack init complete."
