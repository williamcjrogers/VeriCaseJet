#!/bin/bash
# Get OpenSearch endpoint

echo "Getting OpenSearch domain endpoint..."
aws opensearch list-domain-names --region eu-west-2 --query 'DomainNames[*].DomainName' --output text | while read domain; do
  echo ""
  echo "Domain: $domain"
  aws opensearch describe-domain --region eu-west-2 --domain-name $domain --query 'DomainStatus.Endpoint' --output text
done
