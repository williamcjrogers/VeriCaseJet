#!/usr/bin/env python3
"""
Setup script for VeriCase Case Law Knowledge Base.
Creates:
1. IAM Roles
2. OpenSearch Serverless Collection (Vector Store)
3. Bedrock Knowledge Base
4. Bedrock Data Source (S3)

Usage:
    python scripts/setup_caselaw_kb.py
"""

import json
import logging
import os
import sys
import time
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
from botocore.exceptions import ClientError

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vericase.api.app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REGION = settings.AWS_REGION
KB_NAME = "vericase-caselaw-kb"
DS_NAME = "vericase-caselaw-datasource"
BUCKET_NAME = "vericase-caselaw-curated"
COLLECTION_NAME = "vericase-caselaw-vectors"
INDEX_NAME = "caselaw-index"
ROLE_NAME = "VeriCaseBedrockKBRole"
ROLE_POLICY_NAME = "VeriCaseBedrockKBAccess"
USER_POLICY_NAME = "VeriCaseAOSSAccess"
# OpenSearch Serverless policy names must be <= 32 chars.
ENCRYPTION_POLICY_NAME = "vc-caselaw-enc"
NETWORK_POLICY_NAME = "vc-caselaw-net"
ACCESS_POLICY_NAME = "vc-caselaw-data"

# Clients
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
opensearch = boto3.client("opensearchserverless", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
sts = boto3.client("sts", region_name=REGION)


def get_identity():
    identity = sts.get_caller_identity()
    return identity["Account"], identity["Arn"]


def normalize_principal_arn(account_id: str, arn: str) -> str:
    if ":assumed-role/" in arn:
        role_part = arn.split(":assumed-role/", 1)[1]
        role_name = role_part.split("/", 1)[0]
        return f"arn:aws:iam::{account_id}:role/{role_name}"
    return arn


def extract_user_name(arn: str) -> str | None:
    marker = ":user/"
    if marker in arn:
        return arn.split(marker, 1)[1]
    return None


def _is_already_exists(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code", "")
    message = error.response.get("Error", {}).get("Message", "").lower()
    return (
        code in {"ConflictException", "ResourceAlreadyExistsException"}
        or "already exists" in message
    )


def create_iam_role(role_name, assume_role_policy):
    try:
        role = iam.create_role(
            RoleName=role_name, AssumeRolePolicyDocument=json.dumps(assume_role_policy)
        )
        logger.info(f"Created IAM role: {role_name}")
        return role["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role = iam.get_role(RoleName=role_name)
            logger.info(f"IAM role {role_name} already exists")
            return role["Role"]["Arn"]
        raise


def ensure_security_policy(policy_type: str, name: str, policy: dict, description: str):
    try:
        opensearch.create_security_policy(
            name=name,
            type=policy_type,
            policy=json.dumps(policy),
            description=description,
        )
        logger.info(f"Created {policy_type} security policy: {name}")
    except ClientError as e:
        if _is_already_exists(e):
            detail = opensearch.get_security_policy(name=name, type=policy_type)
            version = detail["securityPolicyDetail"]["policyVersion"]
            try:
                opensearch.update_security_policy(
                    name=name,
                    type=policy_type,
                    policy=json.dumps(policy),
                    policyVersion=version,
                    description=description,
                )
                logger.info(f"Updated {policy_type} security policy: {name}")
            except ClientError as update_error:
                update_message = str(update_error)
                if "No changes detected" in update_message:
                    logger.info(
                        "No changes for %s security policy: %s",
                        policy_type,
                        name,
                    )
                    return
                raise
        else:
            raise


def ensure_access_policy(name: str, policy: dict, description: str):
    try:
        opensearch.create_access_policy(
            name=name,
            type="data",
            policy=json.dumps(policy),
            description=description,
        )
        logger.info(f"Created access policy: {name}")
    except ClientError as e:
        if _is_already_exists(e):
            detail = opensearch.get_access_policy(name=name, type="data")
            version = detail["accessPolicyDetail"]["policyVersion"]
            try:
                opensearch.update_access_policy(
                    name=name,
                    type="data",
                    policy=json.dumps(policy),
                    policyVersion=version,
                    description=description,
                )
                logger.info(f"Updated access policy: {name}")
            except ClientError as update_error:
                update_message = str(update_error)
                if "No changes detected" in update_message:
                    logger.info("No changes for access policy: %s", name)
                    return
                raise
        else:
            raise


def get_existing_collection():
    response = opensearch.list_collections()
    for summary in response.get("collectionSummaries", []):
        if summary.get("name") == COLLECTION_NAME:
            return summary
    return None


def wait_for_collection_active(collection_id: str):
    while True:
        status = opensearch.batch_get_collection(ids=[collection_id])
        state = status["collectionDetails"][0]["status"]
        if state == "ACTIVE":
            logger.info("Collection is ACTIVE")
            return
        logger.info(f"Waiting for collection... ({state})")
        time.sleep(10)


def create_opensearch_collection():
    """Create or reuse OpenSearch Serverless Collection"""
    existing = get_existing_collection()
    if existing:
        logger.info("Using existing OpenSearch collection: %s", existing["id"])
        if existing.get("status") != "ACTIVE":
            wait_for_collection_active(existing["id"])
        return existing["id"], existing["arn"]

    try:
        # 1. Create Collection
        response = opensearch.create_collection(
            name=COLLECTION_NAME,
            type="VECTORSEARCH",
            description="VeriCase Case Law Vectors",
        )
        collection_id = response["createCollectionDetail"]["id"]
        collection_arn = response["createCollectionDetail"]["arn"]
        logger.info(f"Creating OpenSearch collection: {collection_id}")

        # Wait for active
        wait_for_collection_active(collection_id)

        return collection_id, collection_arn
    except ClientError as e:
        logger.error(f"Failed to create collection: {e}")
        return None, None


def get_collection_endpoint(collection_id: str) -> str:
    response = opensearch.batch_get_collection(ids=[collection_id])
    details = response["collectionDetails"][0]
    endpoint = details.get("collectionEndpoint")
    if not endpoint:
        raise RuntimeError("OpenSearch collection endpoint not available yet")
    if endpoint.startswith("https://"):
        return endpoint
    return f"https://{endpoint}"


def _opensearch_client(collection_endpoint: str) -> OpenSearch:
    host = collection_endpoint.replace("https://", "").split("/", 1)[0]
    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials not found for OpenSearch auth")

    awsauth = AWSV4SignerAuth(credentials, REGION, "aoss")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def ensure_vector_index(collection_id: str) -> None:
    endpoint = get_collection_endpoint(collection_id)
    _index_url = f"{endpoint}/{INDEX_NAME}"  # noqa: F841

    mapping = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "space_type": "cosinesimil",
                        "parameters": {"ef_construction": 512, "m": 16},
                    },
                },
                "text": {"type": "text"},
                "metadata": {"type": "object"},
            }
        },
    }

    client = _opensearch_client(endpoint)
    if client.indices.exists(index=INDEX_NAME):
        existing = client.indices.get(index=INDEX_NAME)
        try:
            engine = (
                existing[INDEX_NAME]["mappings"]["properties"]["embedding"]
                .get("method", {})
                .get("engine")
            )
        except Exception:
            engine = None

        if engine == "faiss":
            logger.info("OpenSearch index already exists: %s", INDEX_NAME)
            return

        logger.warning(
            "OpenSearch index %s uses engine %s; recreating with FAISS.",
            INDEX_NAME,
            engine or "unknown",
        )
        client.indices.delete(index=INDEX_NAME)

    try:
        client.indices.create(index=INDEX_NAME, body=mapping)
        logger.info("Created OpenSearch index: %s", INDEX_NAME)
    except Exception as e:
        raise RuntimeError(f"Failed to create index {INDEX_NAME}: {e}") from e


def attach_kb_role_policy(role_name: str, collection_arn: str):
    bucket_arn = f"arn:aws:s3:::{BUCKET_NAME}"
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [bucket_arn],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:GetObjectVersion"],
                "Resource": [f"{bucket_arn}/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["aoss:APIAccessAll"],
                "Resource": [collection_arn],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=ROLE_POLICY_NAME,
        PolicyDocument=json.dumps(policy_doc),
    )
    logger.info("Attached inline policy %s to role %s", ROLE_POLICY_NAME, role_name)


def attach_user_policy(user_name: str, collection_arn: str) -> None:
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["aoss:APIAccessAll"],
                "Resource": [collection_arn],
            }
        ],
    }
    iam.put_user_policy(
        UserName=user_name,
        PolicyName=USER_POLICY_NAME,
        PolicyDocument=json.dumps(policy_doc),
    )
    logger.info("Attached inline policy %s to user %s", USER_POLICY_NAME, user_name)


def create_knowledge_base(role_arn, collection_arn):
    """Create Bedrock Knowledge Base"""
    # Define vector store config (OpenSearch Serverless)
    # Note: In a real script, we'd need to create the index first via OSS API
    # For this setup script, we'll assume the index 'caselaw-index' will be created
    payload = {
        "name": KB_NAME,
        "description": "Case Law Intelligence Layer for VeriCase",
        "roleArn": role_arn,
        "knowledgeBaseConfiguration": {
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{REGION}::foundation-model/amazon.titan-embed-text-v2:0"
            },
        },
        "storageConfiguration": {
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": collection_arn,
                "vectorIndexName": INDEX_NAME,
                "fieldMapping": {
                    "vectorField": "embedding",
                    "textField": "text",
                    "metadataField": "metadata",
                },
            },
        },
    }

    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        try:
            response = bedrock_agent.create_knowledge_base(**payload)
            kb_id = response["knowledgeBase"]["knowledgeBaseId"]
            logger.info(f"Created Knowledge Base: {kb_id}")
            return kb_id
        except ClientError as e:
            message = str(e)
            if "security_exception" in message and attempt < max_attempts:
                wait_s = 10 * attempt
                logger.warning(
                    "KB create blocked by OpenSearch policy propagation. Retry %s/%s in %ss.",
                    attempt,
                    max_attempts,
                    wait_s,
                )
                time.sleep(wait_s)
                continue
            logger.error(f"Failed to create KB: {e}")
            return None


def create_data_source(kb_id):
    """Create S3 Data Source for KB"""
    try:
        response = bedrock_agent.create_data_source(
            knowledgeBaseId=kb_id,
            name=DS_NAME,
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{BUCKET_NAME}",
                },
            },
        )
        ds_id = response["dataSource"]["dataSourceId"]
        logger.info(f"Created Data Source: {ds_id}")
        return ds_id
    except ClientError as e:
        logger.error(f"Failed to create Data Source: {e}")
        return None


def main():
    account_id, caller_arn = get_identity()
    logger.info(f"Setting up Case Law KB in {REGION} for account {account_id}")

    # 1. IAM Role for Bedrock
    kb_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    kb_role_arn = create_iam_role(ROLE_NAME, kb_role_policy)

    # 2. OpenSearch security and access policies
    encryption_policy = {
        "Rules": [
            {
                "ResourceType": "collection",
                "Resource": [f"collection/{COLLECTION_NAME}"],
            }
        ],
        "AWSOwnedKey": True,
    }
    ensure_security_policy(
        "encryption",
        ENCRYPTION_POLICY_NAME,
        encryption_policy,
        "Encryption policy for VeriCase Case Law collection",
    )

    network_policy = [
        {
            "Rules": [
                {
                    "ResourceType": "collection",
                    "Resource": [f"collection/{COLLECTION_NAME}"],
                },
                {
                    "ResourceType": "dashboard",
                    "Resource": [f"collection/{COLLECTION_NAME}"],
                },
            ],
            "AllowFromPublic": True,
        }
    ]
    ensure_security_policy(
        "network",
        NETWORK_POLICY_NAME,
        network_policy,
        "Network policy for VeriCase Case Law collection",
    )

    access_principals = [kb_role_arn]
    if caller_arn:
        access_principals.append(normalize_principal_arn(account_id, caller_arn))

    access_policy = [
        {
            "Rules": [
                {
                    "ResourceType": "collection",
                    "Resource": [f"collection/{COLLECTION_NAME}"],
                    "Permission": ["aoss:DescribeCollectionItems"],
                },
                {
                    "ResourceType": "index",
                    "Resource": [f"index/{COLLECTION_NAME}/*"],
                    "Permission": [
                        "aoss:CreateIndex",
                        "aoss:DescribeIndex",
                        "aoss:UpdateIndex",
                        "aoss:DeleteIndex",
                        "aoss:ReadDocument",
                        "aoss:WriteDocument",
                    ],
                },
            ],
            "Principal": access_principals,
        }
    ]
    ensure_access_policy(
        ACCESS_POLICY_NAME,
        access_policy,
        "Data access policy for VeriCase Case Law collection",
    )
    time.sleep(10)

    # 3. OpenSearch Collection
    collection_id, collection_arn = create_opensearch_collection()
    if not collection_arn:
        logger.error("OpenSearch collection could not be created or found.")
        return

    attach_kb_role_policy(ROLE_NAME, collection_arn)
    user_name = extract_user_name(caller_arn or "")
    if user_name:
        try:
            attach_user_policy(user_name, collection_arn)
        except ClientError as e:
            logger.warning("Unable to attach user policy for %s: %s", user_name, e)

    # 4. OpenSearch index (required before KB creation)
    ensure_vector_index(collection_id)

    # 5. Knowledge Base
    kb_id = create_knowledge_base(kb_role_arn, collection_arn)

    if kb_id:
        # 6. Data Source
        create_data_source(kb_id)

        print("\n" + "=" * 50)
        print("SETUP COMPLETE")
        print(f"Knowledge Base ID: {kb_id}")
        print("Add this to your .env file as BEDROCK_KB_ID")
        print("=" * 50)


if __name__ == "__main__":
    main()
