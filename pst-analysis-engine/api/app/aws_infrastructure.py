# AWS Infrastructure as Code for VeriCase
import json

# CloudFormation template for complete AWS infrastructure
VERICASE_CLOUDFORMATION_TEMPLATE = {
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "VeriCase AWS Infrastructure - Complete AI-Powered Legal Evidence Platform",
    "Parameters": {
        "Environment": {
            "Type": "String",
            "Default": "production",
            "AllowedValues": ["development", "staging", "production"],
        },
        "DatabasePassword": {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 12,
            "Description": "RDS PostgreSQL password",
        },
        "DomainName": {
            "Type": "String",
            "Description": "Domain name for the application (e.g., vericase.com)",
        },
    },
    "Resources": {
        # S3 Buckets
        "VeriCaseDocumentsBucket": {
            "Type": "AWS::S3::Bucket",
            "Properties": {
                "BucketName": {
                    "Fn::Sub": "vericase-documents-${Environment}-${AWS::AccountId}"
                },
                "VersioningConfiguration": {"Status": "Enabled"},
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
                "LifecycleConfiguration": {
                    "Rules": [
                        {
                            "Id": "ArchiveOldVersions",
                            "Status": "Enabled",
                            "NoncurrentVersionTransitions": [
                                {"TransitionInDays": 30, "StorageClass": "STANDARD_IA"},
                                {"TransitionInDays": 90, "StorageClass": "GLACIER"},
                            ],
                        }
                    ]
                },
                "NotificationConfiguration": {
                    "EventBridgeConfiguration": {"EventBridgeEnabled": True}
                },
            },
        },
        "VeriCaseKnowledgeBaseBucket": {
            "Type": "AWS::S3::Bucket",
            "Properties": {
                "BucketName": {
                    "Fn::Sub": "vericase-knowledge-base-${Environment}-${AWS::AccountId}"
                },
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
            },
        },
        # RDS PostgreSQL Database
        "VeriCaseDatabase": {
            "Type": "AWS::RDS::DBInstance",
            "Properties": {
                "DBInstanceIdentifier": {"Fn::Sub": "vericase-db-${Environment}"},
                "DBInstanceClass": "db.t3.medium",
                "Engine": "postgres",
                "EngineVersion": "15.4",
                "AllocatedStorage": 100,
                "StorageType": "gp3",
                "StorageEncrypted": True,
                "MasterUsername": "vericase_admin",
                "MasterUserPassword": {"Ref": "DatabasePassword"},
                "DBName": "vericase",
                "VPCSecurityGroups": [{"Ref": "DatabaseSecurityGroup"}],
                "DBSubnetGroupName": {"Ref": "DatabaseSubnetGroup"},
                "BackupRetentionPeriod": 7,
                "MultiAZ": {"Fn::If": ["IsProduction", True, False]},
                "DeletionProtection": {"Fn::If": ["IsProduction", True, False]},
                "EnablePerformanceInsights": True,
                "MonitoringInterval": 60,
                "MonitoringRoleArn": {
                    "Fn::GetAtt": ["RDSEnhancedMonitoringRole", "Arn"]
                },
            },
        },
        # OpenSearch Serverless Collection
        "VeriCaseSearchCollection": {
            "Type": "AWS::OpenSearchServerless::Collection",
            "Properties": {
                "Name": {"Fn::Sub": "vericase-search-${Environment}"},
                "Type": "SEARCH",
                "Description": "VeriCase document search and analytics",
            },
        },
        # Bedrock Knowledge Base
        "VeriCaseKnowledgeBase": {
            "Type": "AWS::Bedrock::KnowledgeBase",
            "Properties": {
                "Name": {"Fn::Sub": "VeriCase-KB-${Environment}"},
                "Description": "VeriCase Legal Evidence Knowledge Base",
                "RoleArn": {"Fn::GetAtt": ["BedrockKnowledgeBaseRole", "Arn"]},
                "KnowledgeBaseConfiguration": {
                    "Type": "VECTOR",
                    "VectorKnowledgeBaseConfiguration": {
                        "EmbeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"
                    },
                },
                "StorageConfiguration": {
                    "Type": "OPENSEARCH_SERVERLESS",
                    "OpensearchServerlessConfiguration": {
                        "CollectionArn": {
                            "Fn::GetAtt": ["VeriCaseSearchCollection", "Arn"]
                        },
                        "VectorIndexName": "vericase-evidence-index",
                        "FieldMapping": {
                            "VectorField": "content_vector",
                            "TextField": "content",
                            "MetadataField": "metadata",
                        },
                    },
                },
            },
        },
        # Bedrock Data Source
        "VeriCaseDataSource": {
            "Type": "AWS::Bedrock::DataSource",
            "Properties": {
                "Name": {"Fn::Sub": "VeriCase-DataSource-${Environment}"},
                "KnowledgeBaseId": {"Ref": "VeriCaseKnowledgeBase"},
                "DataSourceConfiguration": {
                    "Type": "S3",
                    "S3Configuration": {
                        "BucketArn": {
                            "Fn::GetAtt": ["VeriCaseKnowledgeBaseBucket", "Arn"]
                        },
                        "InclusionPrefixes": ["evidence/"],
                    },
                },
            },
        },
        # Lambda Functions
        "TextractProcessorFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "FunctionName": {
                    "Fn::Sub": "vericase-textract-processor-${Environment}"
                },
                "Runtime": "python3.11",
                "Handler": "lambda_function.textract_handler",
                "Code": {"ZipFile": "# Lambda code will be deployed separately"},
                "Timeout": 900,
                "MemorySize": 1024,
                "Role": {"Fn::GetAtt": ["LambdaExecutionRole", "Arn"]},
                "Environment": {
                    "Variables": {
                        "ENVIRONMENT": {"Ref": "Environment"},
                        "DB_HOST": {
                            "Fn::GetAtt": ["VeriCaseDatabase", "Endpoint.Address"]
                        },
                        "DB_NAME": "vericase",
                        "DOCUMENTS_BUCKET": {"Ref": "VeriCaseDocumentsBucket"},
                    }
                },
            },
        },
        "ComprehendAnalyzerFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "FunctionName": {
                    "Fn::Sub": "vericase-comprehend-analyzer-${Environment}"
                },
                "Runtime": "python3.11",
                "Handler": "lambda_function.comprehend_handler",
                "Code": {"ZipFile": "# Lambda code will be deployed separately"},
                "Timeout": 300,
                "MemorySize": 512,
                "Role": {"Fn::GetAtt": ["LambdaExecutionRole", "Arn"]},
            },
        },
        "DocumentClassifierFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "FunctionName": {
                    "Fn::Sub": "vericase-document-classifier-${Environment}"
                },
                "Runtime": "python3.11",
                "Handler": "lambda_function.classifier_handler",
                "Code": {"ZipFile": "# Lambda code will be deployed separately"},
                "Timeout": 300,
                "MemorySize": 512,
                "Role": {"Fn::GetAtt": ["LambdaExecutionRole", "Arn"]},
            },
        },
        "DatabaseUpdaterFunction": {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "FunctionName": {"Fn::Sub": "vericase-database-updater-${Environment}"},
                "Runtime": "python3.11",
                "Handler": "lambda_function.database_handler",
                "Code": {"ZipFile": "# Lambda code will be deployed separately"},
                "Timeout": 300,
                "MemorySize": 256,
                "Role": {"Fn::GetAtt": ["LambdaExecutionRole", "Arn"]},
                "VpcConfig": {
                    "SecurityGroupIds": [{"Ref": "LambdaSecurityGroup"}],
                    "SubnetIds": [{"Ref": "PrivateSubnet1"}, {"Ref": "PrivateSubnet2"}],
                },
            },
        },
        # Step Functions State Machine
        "EvidenceProcessingStateMachine": {
            "Type": "AWS::StepFunctions::StateMachine",
            "Properties": {
                "StateMachineName": {
                    "Fn::Sub": "VeriCase-Evidence-Processing-${Environment}"
                },
                "RoleArn": {"Fn::GetAtt": ["StepFunctionsRole", "Arn"]},
                "DefinitionString": {
                    "Fn::Sub": json.dumps(
                        {
                            "Comment": "VeriCase Evidence Processing Workflow",
                            "StartAt": "ExtractText",
                            "States": {
                                "ExtractText": {
                                    "Type": "Task",
                                    "Resource": "arn:aws:states:::lambda:invoke",
                                    "Parameters": {
                                        "FunctionName": "${TextractProcessorFunction}",
                                        "Payload.$": "$",
                                    },
                                    "Next": "AnalyzeEntities",
                                },
                                "AnalyzeEntities": {
                                    "Type": "Task",
                                    "Resource": "arn:aws:states:::lambda:invoke",
                                    "Parameters": {
                                        "FunctionName": "${ComprehendAnalyzerFunction}",
                                        "Payload.$": "$.Payload",
                                    },
                                    "Next": "ClassifyDocument",
                                },
                                "ClassifyDocument": {
                                    "Type": "Task",
                                    "Resource": "arn:aws:states:::lambda:invoke",
                                    "Parameters": {
                                        "FunctionName": "${DocumentClassifierFunction}",
                                        "Payload.$": "$.Payload",
                                    },
                                    "Next": "UpdateDatabase",
                                },
                                "UpdateDatabase": {
                                    "Type": "Task",
                                    "Resource": "arn:aws:states:::lambda:invoke",
                                    "Parameters": {
                                        "FunctionName": "${DatabaseUpdaterFunction}",
                                        "Payload.$": "$.Payload",
                                    },
                                    "End": True,
                                },
                            },
                        }
                    )
                },
            },
        },
        # EventBridge Custom Bus
        "VeriCaseEventBus": {
            "Type": "AWS::Events::EventBus",
            "Properties": {"Name": {"Fn::Sub": "vericase-events-${Environment}"}},
        },
        # EventBridge Rules
        "EvidenceUploadedRule": {
            "Type": "AWS::Events::Rule",
            "Properties": {
                "EventBusName": {"Ref": "VeriCaseEventBus"},
                "EventPattern": {
                    "source": ["vericase.evidence"],
                    "detail-type": ["Evidence Uploaded"],
                },
                "Targets": [
                    {
                        "Arn": {
                            "Fn::GetAtt": ["EvidenceProcessingStateMachine", "Arn"]
                        },
                        "Id": "EvidenceProcessingTarget",
                        "RoleArn": {"Fn::GetAtt": ["EventBridgeRole", "Arn"]},
                    }
                ],
            },
        },
        # QuickSight Data Set
        "VeriCaseQuickSightDataSet": {
            "Type": "AWS::QuickSight::DataSet",
            "Properties": {
                "AwsAccountId": {"Ref": "AWS::AccountId"},
                "DataSetId": {"Fn::Sub": "vericase-analytics-${Environment}"},
                "Name": "VeriCase Analytics Dataset",
                "PhysicalTableMap": {
                    "evidence_table": {
                        "RelationalTable": {
                            "DataSourceArn": {"Ref": "QuickSightDataSource"},
                            "Schema": "public",
                            "Name": "evidence_items",
                            "InputColumns": [
                                {"Name": "id", "Type": "STRING"},
                                {"Name": "filename", "Type": "STRING"},
                                {"Name": "evidence_type", "Type": "STRING"},
                                {"Name": "document_date", "Type": "DATETIME"},
                                {"Name": "case_id", "Type": "STRING"},
                                {"Name": "project_id", "Type": "STRING"},
                                {"Name": "created_at", "Type": "DATETIME"},
                            ],
                        }
                    }
                },
            },
        },
        # Macie Classification Job
        "MacieClassificationJob": {
            "Type": "AWS::Macie::ClassificationJob",
            "Properties": {
                "JobType": "SCHEDULED",
                "Name": {"Fn::Sub": "VeriCase-Sensitivity-Scan-${Environment}"},
                "Description": "Scan VeriCase documents for sensitive data",
                "S3JobDefinition": {
                    "BucketDefinitions": [
                        {
                            "AccountId": {"Ref": "AWS::AccountId"},
                            "Buckets": [{"Ref": "VeriCaseDocumentsBucket"}],
                        }
                    ]
                },
                "ScheduleFrequency": {"WeeklySchedule": {"DayOfWeek": "SUNDAY"}},
            },
        },
        # IAM Roles
        "LambdaExecutionRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                    "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole",
                ],
                "Policies": [
                    {
                        "PolicyName": "VeriCaseServiceAccess",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "textract:*",
                                        "comprehend:*",
                                        "rekognition:*",
                                        "transcribe:*",
                                        "bedrock:*",
                                    ],
                                    "Resource": "*",
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:GetObject", "s3:PutObject"],
                                    "Resource": [
                                        {"Fn::Sub": "${VeriCaseDocumentsBucket}/*"},
                                        {"Fn::Sub": "${VeriCaseKnowledgeBaseBucket}/*"},
                                    ],
                                },
                            ],
                        },
                    }
                ],
            },
        },
        "BedrockKnowledgeBaseRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "bedrock.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "BedrockKnowledgeBaseAccess",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:GetObject", "s3:ListBucket"],
                                    "Resource": [
                                        {
                                            "Fn::GetAtt": [
                                                "VeriCaseKnowledgeBaseBucket",
                                                "Arn",
                                            ]
                                        },
                                        {"Fn::Sub": "${VeriCaseKnowledgeBaseBucket}/*"},
                                    ],
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": ["aoss:APIAccessAll"],
                                    "Resource": {
                                        "Fn::GetAtt": [
                                            "VeriCaseSearchCollection",
                                            "Arn",
                                        ]
                                    },
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": ["bedrock:InvokeModel"],
                                    "Resource": "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v1",
                                },
                            ],
                        },
                    }
                ],
            },
        },
        "StepFunctionsRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "states.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "StepFunctionsLambdaAccess",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["lambda:InvokeFunction"],
                                    "Resource": [
                                        {
                                            "Fn::GetAtt": [
                                                "TextractProcessorFunction",
                                                "Arn",
                                            ]
                                        },
                                        {
                                            "Fn::GetAtt": [
                                                "ComprehendAnalyzerFunction",
                                                "Arn",
                                            ]
                                        },
                                        {
                                            "Fn::GetAtt": [
                                                "DocumentClassifierFunction",
                                                "Arn",
                                            ]
                                        },
                                        {
                                            "Fn::GetAtt": [
                                                "DatabaseUpdaterFunction",
                                                "Arn",
                                            ]
                                        },
                                    ],
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "EventBridgeRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "events.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "EventBridgeStepFunctionsAccess",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["states:StartExecution"],
                                    "Resource": {
                                        "Fn::GetAtt": [
                                            "EvidenceProcessingStateMachine",
                                            "Arn",
                                        ]
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "RDSEnhancedMonitoringRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "monitoring.rds.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
                ],
            },
        },
        # VPC and Networking (simplified)
        "VPC": {
            "Type": "AWS::EC2::VPC",
            "Properties": {
                "CidrBlock": "10.0.0.0/16",
                "EnableDnsHostnames": True,
                "EnableDnsSupport": True,
                "Tags": [
                    {"Key": "Name", "Value": {"Fn::Sub": "VeriCase-VPC-${Environment}"}}
                ],
            },
        },
        "PrivateSubnet1": {
            "Type": "AWS::EC2::Subnet",
            "Properties": {
                "VpcId": {"Ref": "VPC"},
                "CidrBlock": "10.0.1.0/24",
                "AvailabilityZone": {"Fn::Select": [0, {"Fn::GetAZs": ""}]},
            },
        },
        "PrivateSubnet2": {
            "Type": "AWS::EC2::Subnet",
            "Properties": {
                "VpcId": {"Ref": "VPC"},
                "CidrBlock": "10.0.2.0/24",
                "AvailabilityZone": {"Fn::Select": [1, {"Fn::GetAZs": ""}]},
            },
        },
        "DatabaseSubnetGroup": {
            "Type": "AWS::RDS::DBSubnetGroup",
            "Properties": {
                "DBSubnetGroupDescription": "Subnet group for VeriCase database",
                "SubnetIds": [{"Ref": "PrivateSubnet1"}, {"Ref": "PrivateSubnet2"}],
            },
        },
        "DatabaseSecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Security group for VeriCase database",
                "VpcId": {"Ref": "VPC"},
                "SecurityGroupIngress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 5432,
                        "ToPort": 5432,
                        "SourceSecurityGroupId": {"Ref": "LambdaSecurityGroup"},
                    }
                ],
            },
        },
        "LambdaSecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Security group for VeriCase Lambda functions",
                "VpcId": {"Ref": "VPC"},
            },
        },
    },
    "Conditions": {
        "IsProduction": {"Fn::Equals": [{"Ref": "Environment"}, "production"]}
    },
    "Outputs": {
        "DocumentsBucket": {
            "Description": "S3 bucket for documents",
            "Value": {"Ref": "VeriCaseDocumentsBucket"},
            "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-DocumentsBucket"}},
        },
        "KnowledgeBaseId": {
            "Description": "Bedrock Knowledge Base ID",
            "Value": {"Ref": "VeriCaseKnowledgeBase"},
            "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-KnowledgeBaseId"}},
        },
        "DatabaseEndpoint": {
            "Description": "RDS database endpoint",
            "Value": {"Fn::GetAtt": ["VeriCaseDatabase", "Endpoint.Address"]},
            "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-DatabaseEndpoint"}},
        },
        "StateMachineArn": {
            "Description": "Step Functions state machine ARN",
            "Value": {"Fn::GetAtt": ["EvidenceProcessingStateMachine", "Arn"]},
            "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-StateMachineArn"}},
        },
        "EventBusName": {
            "Description": "EventBridge custom bus name",
            "Value": {"Ref": "VeriCaseEventBus"},
            "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-EventBusName"}},
        },
    },
}

# Terraform equivalent (for those who prefer Terraform)
VERICASE_TERRAFORM_CONFIG = """
# VeriCase AWS Infrastructure - Terraform Configuration

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "database_password" {
  description = "RDS PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "domain_name" {
  description = "Domain name for the application"
  type        = string
}

# S3 Buckets
resource "aws_s3_bucket" "documents" {
  bucket = "vericase-documents-${var.environment}-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_notification" "documents" {
  bucket      = aws_s3_bucket.documents.id
  eventbridge = true
}

# Bedrock Knowledge Base
resource "aws_bedrock_knowledge_base" "vericase" {
  name        = "VeriCase-KB-${var.environment}"
  description = "VeriCase Legal Evidence Knowledge Base"
  role_arn    = aws_iam_role.bedrock_kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn     = aws_opensearchserverless_collection.vericase.arn
      vector_index_name  = "vericase-evidence-index"
      field_mapping {
        vector_field   = "content_vector"
        text_field     = "content"
        metadata_field = "metadata"
      }
    }
  }
}

# Lambda Functions
resource "aws_lambda_function" "textract_processor" {
  filename         = "textract_processor.zip"
  function_name    = "vericase-textract-processor-${var.environment}"
  role            = aws_iam_role.lambda_execution.arn
  handler         = "lambda_function.textract_handler"
  runtime         = "python3.11"
  timeout         = 900
  memory_size     = 1024

  environment {
    variables = {
      ENVIRONMENT      = var.environment
      DOCUMENTS_BUCKET = aws_s3_bucket.documents.bucket
    }
  }
}

# Step Functions State Machine
resource "aws_sfn_state_machine" "evidence_processing" {
  name     = "VeriCase-Evidence-Processing-${var.environment}"
  role_arn = aws_iam_role.step_functions.arn

  definition = jsonencode({
    Comment = "VeriCase Evidence Processing Workflow"
    StartAt = "ExtractText"
    States = {
      ExtractText = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.textract_processor.function_name
          "Payload.$"  = "$"
        }
        Next = "AnalyzeEntities"
      }
      AnalyzeEntities = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.comprehend_analyzer.function_name
          "Payload.$"  = "$.Payload"
        }
        Next = "ClassifyDocument"
      }
      ClassifyDocument = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.document_classifier.function_name
          "Payload.$"  = "$.Payload"
        }
        Next = "UpdateDatabase"
      }
      UpdateDatabase = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.database_updater.function_name
          "Payload.$"  = "$.Payload"
        }
        End = true
      }
    }
  })
}

# Random suffix for unique resource names
resource "random_id" "suffix" {
  byte_length = 4
}

# Outputs
output "documents_bucket" {
  description = "S3 bucket for documents"
  value       = aws_s3_bucket.documents.bucket
}

output "knowledge_base_id" {
  description = "Bedrock Knowledge Base ID"
  value       = aws_bedrock_knowledge_base.vericase.id
}

output "state_machine_arn" {
  description = "Step Functions state machine ARN"
  value       = aws_sfn_state_machine.evidence_processing.arn
}
"""


def generate_deployment_script():
    """Generate deployment script for AWS infrastructure"""
    return """#!/bin/bash
# VeriCase AWS Infrastructure Deployment Script

set -e

echo "🚀 Deploying VeriCase AWS Infrastructure..."

# Set variables
ENVIRONMENT=${1:-production}
STACK_NAME="vericase-infrastructure-$ENVIRONMENT"
REGION=${AWS_REGION:-us-east-1}

# Validate AWS credentials
aws sts get-caller-identity > /dev/null || {
    echo "❌ AWS credentials not configured"
    exit 1
}

# Generate random database password if not provided
if [ -z "$DATABASE_PASSWORD" ]; then
    DATABASE_PASSWORD=$(openssl rand -base64 32)
    echo "📝 Generated database password (save this): $DATABASE_PASSWORD"
fi

# Deploy CloudFormation stack
echo "📦 Deploying CloudFormation stack..."
aws cloudformation deploy \\
    --template-file vericase-infrastructure.yaml \\
    --stack-name $STACK_NAME \\
    --parameter-overrides \\
        Environment=$ENVIRONMENT \\
        DatabasePassword=$DATABASE_PASSWORD \\
        DomainName=${DOMAIN_NAME:-vericase.com} \\
    --capabilities CAPABILITY_IAM \\
    --region $REGION

# Get stack outputs
echo "📋 Getting stack outputs..."
aws cloudformation describe-stacks \\
    --stack-name $STACK_NAME \\
    --region $REGION \\
    --query 'Stacks[0].Outputs' \\
    --output table

# Deploy Lambda functions
echo "🔧 Deploying Lambda functions..."
for function in textract_processor comprehend_analyzer document_classifier database_updater; do
    echo "Deploying $function..."
    zip -r ${function}.zip lambda_functions/${function}/
    aws lambda update-function-code \\
        --function-name vericase-${function}-$ENVIRONMENT \\
        --zip-file fileb://${function}.zip \\
        --region $REGION
done

# Start Bedrock Knowledge Base ingestion
echo "🧠 Starting Knowledge Base ingestion..."
KB_ID=$(aws cloudformation describe-stacks \\
    --stack-name $STACK_NAME \\
    --region $REGION \\
    --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' \\
    --output text)

echo "✅ VeriCase AWS Infrastructure deployed successfully!"
echo "📊 Knowledge Base ID: $KB_ID"
echo "🗄️  Database Password: $DATABASE_PASSWORD"
echo ""
echo "Next steps:"
echo "1. Update your application configuration with the new resource IDs"
echo "2. Run database migrations"
echo "3. Upload initial documents to trigger processing pipeline"
"""
