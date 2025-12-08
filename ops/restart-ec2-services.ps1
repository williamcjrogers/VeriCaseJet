#!/usr/bin/env pwsh
# Restart VeriCase services on EC2 via SSM

$instanceId = "i-0913d878182fa803c"

Write-Host "Restarting VeriCase services on EC2..." -ForegroundColor Cyan

$commandId = aws ssm send-command `
    --instance-ids $instanceId `
    --document-name "AWS-RunShellScript" `
    --parameters "commands=['cd /opt/vericase','git pull','docker-compose -f pst-analysis-engine/docker-compose.yml restart','docker ps']" `
    --query "Command.CommandId" `
    --output text

Start-Sleep -Seconds 10

aws ssm get-command-invocation `
    --command-id $commandId `
    --instance-id $instanceId `
    --query "StandardOutputContent" `
    --output text

Write-Host "`nVeriCase should be available at: http://35.179.167.235:8010" -ForegroundColor Green
