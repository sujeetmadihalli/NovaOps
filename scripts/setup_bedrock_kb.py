"""Setup Amazon Bedrock Knowledge Base for NovaOps v2.

This script:
1. Creates an S3 bucket and uploads skills + runbooks as the knowledge corpus
2. Creates a Bedrock Knowledge Base with Titan Embed V2 as the embedding model
3. Creates an S3 data source and triggers a sync

Prerequisites:
  - AWS credentials configured (same account as Bedrock access)
  - IAM role for Bedrock KB with S3 read access (or script creates one)

Usage:
  python -m scripts.setup_bedrock_kb --allow-managed-kb [--region us-east-1] [--bucket novaops-kb-corpus]

Outputs the KNOWLEDGE_BASE_ID to set in your .env file.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
RUNBOOKS_DIR = PROJECT_ROOT / "runbooks"

# Amazon Titan Text Embeddings V2
EMBEDDING_MODEL_ARN = "arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"

KB_NAME = "novaops-sre-knowledge-base"
DS_NAME = "novaops-skills-runbooks"


def create_bucket(s3, bucket_name: str, region: str) -> str:
    """Create S3 bucket if it doesn't exist."""
    try:
        s3.head_bucket(Bucket=bucket_name)
        logger.info(f"Bucket {bucket_name} already exists")
    except ClientError:
        create_args = {"Bucket": bucket_name}
        if region != "us-east-1":
            create_args["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**create_args)
        logger.info(f"Created bucket: {bucket_name}")
    return bucket_name


def upload_corpus(s3, bucket_name: str):
    """Upload skills and runbooks markdown files to S3."""
    count = 0
    for source_dir, prefix in [(SKILLS_DIR, "skills"), (RUNBOOKS_DIR, "runbooks")]:
        if not source_dir.exists():
            logger.warning(f"Directory not found: {source_dir}")
            continue
        for md_file in source_dir.rglob("*.md"):
            rel_path = md_file.relative_to(source_dir)
            s3_key = f"{prefix}/{str(rel_path).replace(chr(92), '/')}"
            s3.upload_file(str(md_file), bucket_name, s3_key)
            count += 1
            logger.info(f"  Uploaded: s3://{bucket_name}/{s3_key}")

    # Also upload the index.yaml for context
    index_file = SKILLS_DIR / "_meta" / "index.yaml"
    if index_file.exists():
        s3.upload_file(str(index_file), bucket_name, "skills/_meta/index.yaml")
        count += 1

    logger.info(f"Uploaded {count} files to s3://{bucket_name}/")
    return count


def get_or_create_kb_role(iam, bucket_name: str, region: str) -> str:
    """Get or create IAM role for Bedrock Knowledge Base."""
    role_name = "NovaOps-BedrockKB-Role"

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }

    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{bucket_name}",
                    f"arn:aws:s3:::{bucket_name}/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                ],
                "Resource": [
                    EMBEDDING_MODEL_ARN.format(region=region),
                ],
            },
        ],
    }

    try:
        role = iam.get_role(RoleName=role_name)
        role_arn = role["Role"]["Arn"]
        logger.info(f"Using existing role: {role_arn}")
    except ClientError:
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Bedrock KB role for NovaOps SRE knowledge base",
        )
        role_arn = role["Role"]["Arn"]

        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="NovaOps-KB-S3-Access",
            PolicyDocument=json.dumps(s3_policy),
        )
        logger.info(f"Created role: {role_arn}")
        # Wait for role propagation
        logger.info("Waiting 10s for IAM role propagation...")
        time.sleep(10)

    return role_arn


def create_knowledge_base(bedrock_agent, role_arn: str, region: str) -> str:
    """Create Bedrock Knowledge Base or return existing one."""
    # Check if KB already exists
    paginator = bedrock_agent.get_paginator("list_knowledge_bases")
    for page in paginator.paginate():
        for kb in page.get("knowledgeBaseSummaries", []):
            if kb["name"] == KB_NAME:
                kb_id = kb["knowledgeBaseId"]
                logger.info(f"Knowledge Base already exists: {kb_id}")
                return kb_id

    response = bedrock_agent.create_knowledge_base(
        name=KB_NAME,
        description="NovaOps SRE knowledge base — runbooks, playbooks, and incident learnings",
        roleArn=role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": EMBEDDING_MODEL_ARN.format(region=region),
            },
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": "auto",  # Bedrock creates the collection
                "fieldMapping": {
                    "metadataField": "metadata",
                    "textField": "text",
                    "vectorField": "vector",
                },
                "vectorIndexName": "novaops-index",
            },
        },
    )

    kb_id = response["knowledgeBase"]["knowledgeBaseId"]
    logger.info(f"Created Knowledge Base: {kb_id}")

    # Wait for KB to be active
    for _ in range(30):
        kb = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        status = kb["knowledgeBase"]["status"]
        if status == "ACTIVE":
            break
        logger.info(f"KB status: {status}, waiting...")
        time.sleep(5)

    return kb_id


def create_data_source(bedrock_agent, kb_id: str, bucket_name: str) -> str:
    """Create S3 data source for the Knowledge Base."""
    # Check existing
    sources = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
    for ds in sources.get("dataSourceSummaries", []):
        if ds["name"] == DS_NAME:
            ds_id = ds["dataSourceId"]
            logger.info(f"Data source already exists: {ds_id}")
            return ds_id

    response = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name=DS_NAME,
        description="NovaOps skills and runbooks",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{bucket_name}",
            },
        },
    )

    ds_id = response["dataSource"]["dataSourceId"]
    logger.info(f"Created data source: {ds_id}")
    return ds_id


def sync_data_source(bedrock_agent, kb_id: str, ds_id: str):
    """Trigger ingestion sync for the data source."""
    response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job_id = response["ingestionJob"]["ingestionJobId"]
    logger.info(f"Started ingestion job: {job_id}")

    # Wait for sync
    for _ in range(60):
        job = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            ingestionJobId=job_id,
        )
        status = job["ingestionJob"]["status"]
        if status == "COMPLETE":
            stats = job["ingestionJob"].get("statistics", {})
            logger.info(f"Ingestion complete: {stats}")
            return
        if status == "FAILED":
            logger.error(f"Ingestion failed: {job['ingestionJob'].get('failureReasons', [])}")
            return
        logger.info(f"Ingestion status: {status}, waiting...")
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Setup Bedrock Knowledge Base for NovaOps")
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    parser.add_argument("--bucket", default="novaops-sre-kb-corpus")
    parser.add_argument(
        "--allow-managed-kb",
        action="store_true",
        help="Explicit opt-in for managed Knowledge Base resources that can consume hackathon credits.",
    )
    args = parser.parse_args()

    region = args.region
    bucket_name = args.bucket

    if not args.allow_managed_kb:
        logger.error(
            "Refusing to create managed Bedrock Knowledge Base resources without --allow-managed-kb. "
            "For hackathon use, prefer local retrieval in tools/retrieve_knowledge.py."
        )
        sys.exit(2)

    logger.info(f"Setting up Bedrock Knowledge Base in {region}")
    logger.info(f"S3 bucket: {bucket_name}")

    s3 = boto3.client("s3", region_name=region)
    iam = boto3.client("iam")
    bedrock_agent = boto3.client("bedrock-agent", region_name=region)

    # Step 1: Create bucket and upload corpus
    create_bucket(s3, bucket_name, region)
    file_count = upload_corpus(s3, bucket_name)
    if file_count == 0:
        logger.error("No files to upload. Check skills/ and runbooks/ directories.")
        sys.exit(1)

    # Step 2: Create IAM role
    role_arn = get_or_create_kb_role(iam, bucket_name, region)

    # Step 3: Create Knowledge Base
    kb_id = create_knowledge_base(bedrock_agent, role_arn, region)

    # Step 4: Create data source
    ds_id = create_data_source(bedrock_agent, kb_id, bucket_name)

    # Step 5: Sync
    sync_data_source(bedrock_agent, kb_id, ds_id)

    # Output
    print(f"\n{'='*60}")
    print(f"  Bedrock Knowledge Base Setup Complete")
    print(f"{'='*60}")
    print(f"\n  KNOWLEDGE_BASE_ID={kb_id}")
    print(f"\n  Add to your .env file:")
    print(f"    KNOWLEDGE_BASE_ID={kb_id}")
    print(f"    NOVAOPS_USE_MOCK=false")
    print(f"\n  To re-sync after adding new runbooks:")
    print(f"    python -m scripts.setup_bedrock_kb --region {region} --bucket {bucket_name}")
    print()


if __name__ == "__main__":
    main()
