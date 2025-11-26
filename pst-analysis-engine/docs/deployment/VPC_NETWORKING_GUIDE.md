# VPC Networking Configuration for VeriCase App Runner

## Overview
This guide covers the critical VPC networking setup required for App Runner to connect to your private AWS resources (RDS, Redis, OpenSearch).

## Why VPC Connector is Required
App Runner runs in an AWS-managed VPC by default. To access your private resources (RDS, Redis, OpenSearch) in your own VPC, you must configure a VPC connector.

## Configuration Details

### Your VPC
```
VPC ID: vpc-0880b8ccf488f327e
Region: eu-west-2 (London)
```

### Subnet Selection
You must select **at least 2 subnets** in **different Availability Zones** for high availability.

**Example Configuration:**
```
Subnet 1: subnet-xxxxx (eu-west-2a)
Subnet 2: subnet-yyyyy (eu-west-2b)
```

**How to find your subnets:**
1. Go to VPC Console → Subnets
2. Filter by VPC ID: `vpc-0880b8ccf488f327e`
3. Select subnets from different AZs
4. Ensure they have routes to NAT Gateway or Internet Gateway (for outbound internet access)

## Security Group Configuration

### Create a Security Group for App Runner
1. Go to EC2 Console → Security Groups
2. Click "Create security group"
3. **Name**: `apprunner-vericase-sg`
4. **Description**: "Security group for VeriCase App Runner service"
5. **VPC**: Select `vpc-0880b8ccf488f327e`

### Required Outbound Rules

#### Rule 1: PostgreSQL (RDS)
```
Type: PostgreSQL
Protocol: TCP
Port: 5432
Destination: <RDS Security Group ID>
Description: Database access for VeriCase
```

**How to find RDS Security Group:**
1. Go to RDS Console → Databases
2. Click on `database-1` 
3. Look for "VPC security groups" section
4. Note the security group ID (e.g., `sg-xxxxx`)

#### Rule 2: Redis (ElastiCache)
```
Type: Custom TCP
Protocol: TCP
Port: 6379
Destination: <Redis Security Group ID>
Description: Cache access for VeriCase
```

**How to find Redis Security Group:**
1. Go to ElastiCache Console → Redis clusters
2. Click on `vericase-redis`
3. Look for "Security groups" section
4. Note the security group ID (e.g., `sg-yyyyy`)

#### Rule 3: OpenSearch
```
Type: HTTPS
Protocol: TCP
Port: 443
Destination: <OpenSearch Endpoint or Security Group>
Description: Search service access
```

**OpenSearch Endpoint:**
```
vpc-vericase-opensearch-sl2a3zd5dnrbt64bssyocnrofu.eu-west-2.es.amazonaws.com
```

For OpenSearch in VPC, you may need to:
- Use the security group ID of OpenSearch domain, OR
- Use CIDR blocks that include OpenSearch's private IPs, OR
- Use `0.0.0.0/0` for HTTPS (443) if OpenSearch is in same VPC

#### Rule 4: S3 and External APIs
```
Type: All traffic
Protocol: All
Port: All
Destination: 0.0.0.0/0
Description: S3, AI APIs, and external service access
```

**Why this is needed:**
- S3 access (via AWS PrivateLink or public endpoint)
- AI API calls (OpenAI, Anthropic, Google, etc.)
- Email sending (SMTP)
- Any other external services

### Inbound Rules
**App Runner does NOT need inbound rules** in this security group. Inbound traffic to App Runner is handled by AWS at the service level.

## Update RDS, Redis, and OpenSearch Security Groups

### Important: Add Inbound Rules to Your Resource Security Groups

#### RDS Security Group
Add inbound rule:
```
Type: PostgreSQL
Protocol: TCP
Port: 5432
Source: <App Runner Security Group ID>
Description: Allow App Runner access
```

#### Redis Security Group
Add inbound rule:
```
Type: Custom TCP
Protocol: TCP  
Port: 6379
Source: <App Runner Security Group ID>
Description: Allow App Runner access
```

#### OpenSearch Security Group (if applicable)
Add inbound rule:
```
Type: HTTPS
Protocol: TCP
Port: 443
Source: <App Runner Security Group ID>
Description: Allow App Runner access
```

## Verification Checklist

Before deploying, verify:

- [ ] VPC `vpc-0880b8ccf488f527e` is selected
- [ ] At least 2 subnets from different AZs are selected
- [ ] Subnets have routes to NAT Gateway/Internet Gateway
- [ ] App Runner security group has outbound rules for:
  - [ ] PostgreSQL (5432) to RDS
  - [ ] Redis (6379) to ElastiCache
  - [ ] HTTPS (443) to OpenSearch
  - [ ] All traffic (0.0.0.0/0) for S3 and APIs
- [ ] RDS security group allows inbound from App Runner SG
- [ ] Redis security group allows inbound from App Runner SG
- [ ] OpenSearch security group allows inbound from App Runner SG (if in VPC)

## Troubleshooting

### Connection Timeout Errors
**Symptom:** App cannot connect to RDS/Redis/OpenSearch
**Solution:**
1. Verify VPC connector is enabled
2. Check security group outbound rules
3. Verify resource security groups allow inbound from App Runner
4. Check subnet routing tables

### Database Connection Refused
**Symptom:** "Connection refused" errors in logs
**Solution:**
1. Verify RDS is in the same VPC
2. Check RDS security group inbound rules
3. Verify DATABASE_URL is correct
4. Ensure RDS is publicly accessible is OFF (should be private)

### Redis Connection Issues
**Symptom:** Cannot connect to Redis cluster
**Solution:**
1. Verify Redis endpoint URL is correct
2. Check Redis security group inbound rules
3. Ensure Redis is in cluster mode and encryption is configured correctly

### OpenSearch Connection Issues
**Symptom:** Cannot reach OpenSearch
**Solution:**
1. Verify OpenSearch domain is in VPC (not public)
2. Check OpenSearch security group
3. Verify OpenSearch credentials
4. Ensure HTTPS (443) is allowed in App Runner security group

## Cost Considerations

**VPC Connector Costs:**
- Data processing: $0.015 per GB
- Estimated cost for typical usage: $10-30/month

**Tips to minimize costs:**
- Use VPC endpoints for S3 (free, reduces data transfer)
- Place all resources in same region
- Monitor data transfer in CloudWatch

## Security Best Practices

1. **Principle of Least Privilege**: Only allow necessary ports
2. **Use Security Group IDs**: Reference other security groups instead of CIDR blocks when possible
3. **No Public Access**: Keep RDS, Redis, and OpenSearch private (no public endpoints)
4. **Regular Audits**: Review security group rules quarterly
5. **Enable VPC Flow Logs**: Monitor network traffic for anomalies

## Next Steps

After VPC configuration:
1. Deploy your App Runner service
2. Monitor initial connection in CloudWatch Logs
3. Test database connectivity
4. Verify Redis caching works
5. Check OpenSearch indexing

---

**Need Help?**
- AWS Support: Check VPC connector documentation
- VeriCase Support: Review application logs in App Runner console

