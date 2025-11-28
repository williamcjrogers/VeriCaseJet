#!/bin/bash
# Launch VeriCase EC2 instance

aws ec2 run-instances \
  --image-id ami-0c7217cdde317cfec \
  --instance-type t3.large \
  --key-name YOUR_KEY_NAME \
  --security-groups vericase-sg \
  --user-data file://ec2-userdata.sh \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=vericase-prod}]' \
  --output json | tee instance.json

# Extract instance ID
INSTANCE_ID=$(jq -r '.Instances[0].InstanceId' instance.json)
echo "Instance ID: $INSTANCE_ID"

# Wait for instance to be running
echo "Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "Public IP: $PUBLIC_IP"
echo "SSH: ssh -i ~/.ssh/YOUR_KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo "Deploy: ./deploy-to-ec2.sh $PUBLIC_IP ~/.ssh/YOUR_KEY_NAME.pem"
