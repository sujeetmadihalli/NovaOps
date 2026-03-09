#!/bin/bash
echo "Initializing local AWS infrastructure in LocalStack..."

# Wait for LocalStack to be fully ready
awslocal s3 mb s3://novaops-pir-reports

echo "S3 Bucket 'novaops-pir-reports' created successfully!"
echo "LocalStack initialization complete."
