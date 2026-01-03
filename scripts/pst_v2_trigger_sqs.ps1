param(
  [Parameter(Mandatory = $true)]
  [string]$PstFileId,

  [Parameter(Mandatory = $false)]
  [string]$ProjectId,

  [Parameter(Mandatory = $false)]
  [string]$CaseId,

  [Parameter(Mandatory = $false)]
  [string]$FileName,

  [Parameter(Mandatory = $false)]
  [string]$SourceBucket = "vericase-docs",

  [Parameter(Mandatory = $false)]
  [string]$SourceKey,

  [Parameter(Mandatory = $false)]
  [string]$OutputBucket,

  [Parameter(Mandatory = $false)]
  [string]$OutputPrefix,

  [Parameter(Mandatory = $false)]
  [string]$QueueName = "vericase-pst-ingest-v2",

  [Parameter(Mandatory = $false)]
  [string]$Region = "eu-west-2"
)

$ErrorActionPreference = "Stop"

if ((-not $ProjectId -or $ProjectId.Trim().Length -eq 0) -and (-not $CaseId -or $CaseId.Trim().Length -eq 0)) {
  throw "You must provide either -ProjectId or -CaseId."
}

if (-not $SourceKey -or $SourceKey.Trim().Length -eq 0) {
  if (-not $FileName -or $FileName.Trim().Length -eq 0) {
    throw "You must provide -SourceKey OR provide -FileName so SourceKey can be derived."
  }

  if ($ProjectId -and $ProjectId.Trim().Length -gt 0) {
    $SourceKey = ("project_{0}/pst/{1}/{2}" -f $ProjectId, $PstFileId, $FileName)
  } else {
    $SourceKey = ("case_{0}/pst/{1}/{2}" -f $CaseId, $PstFileId, $FileName)
  }
}

if (-not $OutputBucket -or $OutputBucket.Trim().Length -eq 0) {
  $OutputBucket = $SourceBucket
}
if (-not $OutputPrefix -or $OutputPrefix.Trim().Length -eq 0) {
  $OutputPrefix = ("pst-v2/{0}/" -f $PstFileId)
}

$queueUrl = aws sqs get-queue-url --region $Region --queue-name $QueueName --query QueueUrl --output text
if (-not $queueUrl -or $queueUrl.Trim().Length -eq 0) {
  throw "Failed to resolve SQS QueueUrl for queue '$QueueName' in region '$Region'"
}

$body = @{
  pst_file_id   = $PstFileId
  project_id    = $ProjectId
  case_id       = $CaseId
  source_bucket = $SourceBucket
  source_key    = $SourceKey
  output_bucket = $OutputBucket
  output_prefix = $OutputPrefix
} | ConvertTo-Json -Compress

$messageId = aws sqs send-message --region $Region --queue-url $queueUrl --message-body $body --query MessageId --output text

Write-Output ("QueueUrl:  {0}" -f $queueUrl)
Write-Output ("MessageId: {0}" -f $messageId)
Write-Output ("Body:      {0}" -f $body)


