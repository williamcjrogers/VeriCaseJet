variable "aws_region" {
  type        = string
  description = "AWS region"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix"
  default     = "vericase"
}

variable "queue_visibility_timeout_seconds" {
  type        = number
  description = "SQS visibility timeout (seconds)"
  default     = 900
}

variable "queue_message_retention_seconds" {
  type        = number
  description = "SQS retention (seconds)"
  default     = 1209600 # 14 days
}

variable "batch_job_queue_arn" {
  type        = string
  description = "ARN of the AWS Batch job queue used by the PST pipeline"
}

variable "extract_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for the compiled PST extractor"
}

variable "load_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for the loader (COPY into Postgres/Aurora)"
}

variable "thread_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for threading"
}

variable "dedupe_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for dedupe"
}

variable "index_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for indexing (OpenSearch)"
}

