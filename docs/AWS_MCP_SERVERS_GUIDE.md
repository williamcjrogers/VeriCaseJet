# AWS MCP Servers Installation Guide

## Overview
This project now includes 40+ AWS MCP servers that provide comprehensive AWS service integration through the Model Context Protocol (MCP).

## Currently Installing AWS MCP Servers

### Core & Infrastructure (2)
- **awslabs.core-mcp-server** - Core AWS functionality and utilities
- **awslabs.ccapi-mcp-server** - AWS CloudControl API for infrastructure management

### Compute & Container Services (5)
- **awslabs.ec2-mcp-server** - EC2 instance management
- **awslabs.lambda-mcp-server** - Lambda function operations
- **awslabs.ecs-mcp-server** - ECS container orchestration
- **awslabs.eks-mcp-server** - EKS Kubernetes cluster management
- **awslabs-fargate-mcp-server** - AWS Fargate serverless containers

### Storage Services (4)
- **awslabs-s3-mcp-server** - S3 bucket and object operations
- **awslabs-rds-mcp-server** - RDS database management
- **awslabs-ebs-mcp-server** - EBS volume operations
- **awslabs-efs-mcp-server** - EFS file system management

### Database Services (4)
- **awslabs.dynamodb-mcp-server** - DynamoDB NoSQL operations
- **awslabs.postgres-mcp-server** - PostgreSQL database operations
- **awslabs.mysql-mcp-server** - MySQL database operations
- **awslabs.documentdb-mcp-server** - DocumentDB MongoDB-compatible operations

### Monitoring & Logging (1)
- **awslabs.cloudwatch-mcp-server** - CloudWatch metrics and alarms

### Infrastructure as Code (3)
- **awslabs.cdk-mcp-server** - AWS CDK infrastructure definitions
- **awslabs.terraform-mcp-server** - Terraform IaC operations
- **awslabs.iac-mcp-server** - Generic IaC utilities

### Security & Identity (1)
- **awslabs.iam-mcp-server** - IAM user, role, and policy management

### Cost Management (4)
- **awslabs.cost-explorer-mcp-server** - Cost analysis and reporting
- **awslabs.cost-analysis-mcp-server** - Advanced cost analytics
- **awslabs.billing-cost-management-mcp-server** - Billing operations
- **awslabs.aws-pricing-mcp-server** - AWS service pricing information

### AI/ML Services (2)
- **awslabs.bedrock-kb-retrieval-mcp-server** - Amazon Bedrock knowledge base retrieval
- **awslabs.sagemaker-ai-mcp-server** - SageMaker ML model operations

## Not Currently Available (Yanked or Missing)
The following servers were found but are not installable:
- awslabs.cloudwatch-logs-mcp-server
- awslabs.cloudtrail-mcp-server
- awslabs-aws-cloudformation-mcp-server
- awslabs.amazon-rekognition-mcp-server
- awslabs.amazon-bedrock-agentcore-mcp-server
- awslabs.aws-network-mcp-server
- awslabs.aws-documentation-mcp-server
- awslabs.aws-support-mcp-server
- awslabs.github-actions-mcp-server
- awslabs.code-doc-gen-mcp-server
- awslabs.amazon-sns-sqs-mcp-server
- awslabs.kinesis-mcp-server
- awslabs.aws-appsync-mcp-server
- awslabs.aws-serverless-mcp-server
- awslabs.stepfunctions-tool-mcp-server
- awslabs.aws-diagram-mcp-server

## Additional Available Servers (Not Yet Installed)
Over 100+ AWS MCP servers exist on PyPI. Some notable ones include:
- awslabs.amazon-neptune-mcp-server
- awslabs.aws-healthomics-mcp-server
- awslabs.redshift-mcp-server
- awslabs.elasticache-mcp-server
- awslabs.prometheus-mcp-server
- awslabs.valkey-mcp-server
- awslabs.aurora-dsql-mcp-server
- awslabs.timestream-mcp-server
- awslabs.healthlake-mcp-server

## Usage

### Starting MCP Servers in VS Code
1. Press `Ctrl+Shift+P` to open Command Palette
2. Type "MCP: List Servers"
3. Select the servers you want to start
4. Servers will be available in your AI assistant context

### Configuration
All servers are configured in `.vscode/mcp.json` with:
- AWS Profile: `default` (configurable)
- AWS Region: `eu-west-2` (configurable)
- Virtual Environment: `${workspaceFolder}/.venv`

### Environment Variables
Most AWS MCP servers use these environment variables:
- `AWS_PROFILE` - AWS CLI profile to use
- `AWS_REGION` - AWS region for operations
- `FASTMCP_LOG_LEVEL` - Logging level (default: ERROR)

## Use Cases for VeriCase Project

### Cost Optimization
- Use cost-explorer and pricing servers to analyze AWS spending
- Track EC2, RDS, and S3 costs
- Optimize resource allocation

### Infrastructure Management
- Monitor EC2 instances hosting VeriCase application
- Manage RDS PostgreSQL database
- Handle S3 storage for PST files and evidence

### Security & Compliance
- IAM server for access control
- CloudWatch for monitoring and alerts
- Cost management for budget tracking

### AI/ML Integration
- Bedrock KB retrieval for document analysis
- SageMaker for custom ML models
- PostgreSQL server for database operations

### DevOps Automation
- Lambda for serverless functions
- ECS/Fargate for containerized deployments
- Terraform/CDK for infrastructure as code

## Installation Status
See installation log for current status. Installation typically takes 15-30 minutes due to complex dependency resolution.

## Troubleshooting

### Installation Takes Too Long
- Normal for first install (dependency resolution)
- Pip is trying multiple version combinations
- Can install in smaller batches if needed

### Package Conflicts
- Some packages have strict version requirements
- Pip will find compatible versions automatically
- May downgrade some existing packages

### Missing Packages
- Some AWS MCP servers are yanked or unavailable
- These are commented out in requirements.txt
- Check PyPI for newer versions

## Documentation
- AWS MCP Servers: https://github.com/awslabs/
- MCP Protocol: https://modelcontextprotocol.io/
- AWS Documentation: https://docs.aws.amazon.com/

## Next Steps After Installation
1. Restart VS Code to load new MCP servers
2. Configure AWS credentials if not already set
3. Test servers with simple queries
4. Integrate into VeriCase AI workflows
5. Set up cost monitoring and alerts
