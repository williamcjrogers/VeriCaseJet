output "pst_ingest_queue_url" {
  value       = aws_sqs_queue.queue.url
  description = "SQS queue URL for PST ingest V2"
}

output "pst_ingest_queue_arn" {
  value       = aws_sqs_queue.queue.arn
  description = "SQS queue ARN for PST ingest V2"
}

output "pst_ingest_dlq_url" {
  value       = aws_sqs_queue.dlq.url
  description = "SQS DLQ URL for PST ingest V2"
}

output "pst_state_machine_arn" {
  value       = aws_sfn_state_machine.pst_ingest.arn
  description = "Step Functions state machine ARN"
}

