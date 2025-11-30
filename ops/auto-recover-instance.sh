#!/bin/bash
# Auto-recover EC2 instance when it fails health checks

INSTANCE_ID="i-0ade6dff1811bdbcb"
REGION="eu-west-2"

# Create CloudWatch alarm to auto-recover
aws cloudwatch put-metric-alarm \
  --alarm-name vericase-auto-recover \
  --alarm-description "Auto-recover vericase instance on failure" \
  --metric-name StatusCheckFailed_Instance \
  --namespace AWS/EC2 \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --alarm-actions arn:aws:automate:$REGION:ec2:recover \
  --region $REGION

echo "✅ Auto-recovery enabled"
