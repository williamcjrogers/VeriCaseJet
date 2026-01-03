provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  queue_name     = "${var.name_prefix}-pst-ingest-v2"
  dlq_name       = "${var.name_prefix}-pst-ingest-v2-dlq"
  sfn_name       = "${var.name_prefix}-pst-ingest-v2"
  pipe_name      = "${var.name_prefix}-pst-ingest-v2-pipe"
  log_group_name = "/aws/states/${var.name_prefix}-pst-ingest-v2"

  sfn_definition_template = var.pipeline_mode == "single" ? "${path.module}/statemachine.single.asl.json.tftpl" : "${path.module}/statemachine.asl.json.tftpl"
  sfn_definition_vars = var.pipeline_mode == "single" ? {
    batch_job_queue_arn        = var.batch_job_queue_arn
    process_job_definition_arn = var.process_job_definition_arn
  } : {
    batch_job_queue_arn        = var.batch_job_queue_arn
    extract_job_definition_arn = var.extract_job_definition_arn
    load_job_definition_arn    = var.load_job_definition_arn
    thread_job_definition_arn  = var.thread_job_definition_arn
    dedupe_job_definition_arn  = var.dedupe_job_definition_arn
    index_job_definition_arn   = var.index_job_definition_arn
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = local.dlq_name
  message_retention_seconds = var.queue_message_retention_seconds
}

resource "aws_sqs_queue" "queue" {
  name                      = local.queue_name
  message_retention_seconds = var.queue_message_retention_seconds
  visibility_timeout_seconds = var.queue_visibility_timeout_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = local.log_group_name
  retention_in_days = 30
}

resource "aws_iam_role" "pipe_role" {
  name = "${var.name_prefix}-pst-pipe-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = { Service = "pipes.amazonaws.com" }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "pipe_policy" {
  name = "PipePermissions"
  role = aws_iam_role.pipe_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:GetQueueUrl",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.queue.arn
      },
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = aws_sfn_state_machine.pst_ingest.arn
      }
    ]
  })
}

resource "aws_iam_role" "sfn_role" {
  name = "${var.name_prefix}-pst-sfn-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "sfn_policy" {
  name = "BatchPermissions"
  role = aws_iam_role.sfn_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "batch:SubmitJob",
          "batch:DescribeJobs",
          "batch:TerminateJob"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "events:PutTargets",
          "events:PutRule",
          "events:DescribeRule",
          "events:DeleteRule",
          "events:RemoveTargets",
          "events:ListTargetsByRule"
        ]
        Resource = [
          "arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForBatchJobsRule"
        ]
      }
    ]
  })
}

resource "aws_sfn_state_machine" "pst_ingest" {
  name     = local.sfn_name
  role_arn = aws_iam_role.sfn_role.arn

  definition = templatefile(local.sfn_definition_template, local.sfn_definition_vars)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                 = "ALL"
  }
}

resource "aws_pipes_pipe" "sqs_to_sfn" {
  name     = local.pipe_name
  role_arn = aws_iam_role.pipe_role.arn
  source   = aws_sqs_queue.queue.arn
  target   = aws_sfn_state_machine.pst_ingest.arn

  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }

  target_parameters {
    # Ensure Step Functions receives the SQS message body as the execution input (body is JSON text).
    # This avoids the common sharp-edge where the full SQS envelope is passed and $.pst_file_id fails.
    input_template = "<$.body>"
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }

  dead_letter_config {
    arn = aws_sqs_queue.dlq.arn
  }
}

