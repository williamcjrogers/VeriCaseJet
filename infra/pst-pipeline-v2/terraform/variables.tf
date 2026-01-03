variable "aws_region" {
  type        = string
  description = "AWS region"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix"
  default     = "vericase"
}

variable "pipeline_mode" {
  type        = string
  description = "State machine mode: 'single' runs one Batch job (Phase 1). 'multistage' runs Extract/Load/Thread/Dedupe/Index (future)."
  default     = "single"
  validation {
    condition     = contains(["single", "multistage"], var.pipeline_mode)
    error_message = "pipeline_mode must be 'single' or 'multistage'."
  }
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

variable "process_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for Phase 1 single-stage PST processing (UltimatePSTProcessor). Required when pipeline_mode='single'."
  default     = ""
  validation {
    condition     = var.pipeline_mode != "single" || length(var.process_job_definition_arn) > 0
    error_message = "process_job_definition_arn is required when pipeline_mode='single'."
  }
}

variable "extract_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for the compiled PST extractor"
  default     = ""
  validation {
    condition     = var.pipeline_mode != "multistage" || length(var.extract_job_definition_arn) > 0
    error_message = "extract_job_definition_arn is required when pipeline_mode='multistage'."
  }
}

variable "load_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for the loader (COPY into Postgres/Aurora)"
  default     = ""
  validation {
    condition     = var.pipeline_mode != "multistage" || length(var.load_job_definition_arn) > 0
    error_message = "load_job_definition_arn is required when pipeline_mode='multistage'."
  }
}

variable "thread_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for threading"
  default     = ""
  validation {
    condition     = var.pipeline_mode != "multistage" || length(var.thread_job_definition_arn) > 0
    error_message = "thread_job_definition_arn is required when pipeline_mode='multistage'."
  }
}

variable "dedupe_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for dedupe"
  default     = ""
  validation {
    condition     = var.pipeline_mode != "multistage" || length(var.dedupe_job_definition_arn) > 0
    error_message = "dedupe_job_definition_arn is required when pipeline_mode='multistage'."
  }
}

variable "index_job_definition_arn" {
  type        = string
  description = "ARN of the Batch job definition for indexing (OpenSearch)"
  default     = ""
  validation {
    condition     = var.pipeline_mode != "multistage" || length(var.index_job_definition_arn) > 0
    error_message = "index_job_definition_arn is required when pipeline_mode='multistage'."
  }
}

