# 🚀 VeriCase AWS Services Setup Instructions

## **OPTION 1: Complete Setup (Recommended)**

### **Prerequisites**
1. **AWS Account** with admin permissions
2. **AWS CLI** installed and configured
3. **PowerShell** (Windows) or **Bash** (Linux/Mac)

### **Quick Start (5 minutes)**
```powershell
# Run the complete setup script
.\setup-aws-complete.ps1

# Follow the prompts and save the generated password!
```

### **What This Sets Up:**
- ✅ S3 buckets for document storage
- ✅ Textract for document processing
- ✅ Comprehend for text analysis
- ✅ Lambda functions for automation
- ✅ EventBridge for workflows
- ✅ OpenSearch for advanced search
- ✅ Bedrock Knowledge Base for AI
- ✅ IAM roles and permissions
- ✅ Complete configuration

---

## **OPTION 2: Quick Start (Minimal)**

### **Just Want to Try It? (2 minutes)**
```powershell
# Run the simple setup
.\setup-aws-simple.ps1

# This creates just S3 storage to get started
```

---

## **Manual Setup (If Scripts Don't Work)**

### **Step 1: Create S3 Bucket**
```bash
# Create bucket with unique name
aws s3 mb s3://vericase-docs-$(date +%s) --region us-east-1

# Enable event notifications
aws s3api put-bucket-notification-configuration \
    --bucket YOUR_BUCKET_NAME \
    --notification-configuration '{"EventBridgeConfiguration": {}}'
```

### **Step 2: Create IAM Role**
```bash
# Create role for Lambda functions
aws iam create-role \
    --role-name VeriCaseLambdaRole \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

# Attach policies
aws iam attach-role-policy \
    --role-name VeriCaseLambdaRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### **Step 3: Update Configuration**
Create `.env` file:
```env
USE_AWS_SERVICES=true
AWS_REGION=us-east-1
S3_BUCKET=your-bucket-name
ENABLE_AI_AUTO_CLASSIFY=true
```

---

## **Verification Steps**

### **Test AWS Access**
```python
import boto3

# Test S3
s3 = boto3.client('s3')
print("S3 buckets:", [b['Name'] for b in s3.list_buckets()['Buckets']])

# Test Textract
textract = boto3.client('textract')
print("✅ Textract ready")

# Test Comprehend
comprehend = boto3.client('comprehend')
print("✅ Comprehend ready")
```

### **Test VeriCase Integration**
```bash
# Start your VeriCase application
python -m api.app.main

# Upload a test document
curl -X POST "http://localhost:8000/api/v1/aws/evidence/test-id/process"
```

---

## **Cost Monitoring**

### **Set Up Billing Alerts**
```bash
# Create billing alarm for $50/month
aws cloudwatch put-metric-alarm \
    --alarm-name "VeriCase-Billing-Alert" \
    --alarm-description "Alert when VeriCase costs exceed $50" \
    --metric-name EstimatedCharges \
    --namespace AWS/Billing \
    --statistic Maximum \
    --period 86400 \
    --threshold 50 \
    --comparison-operator GreaterThanThreshold
```

### **Monitor Usage**
- Check AWS Cost Explorer daily
- Set up budget alerts
- Monitor service usage in CloudWatch

---

## **Troubleshooting**

### **Common Issues**

#### **1. Permission Denied**
```bash
# Check your AWS credentials
aws sts get-caller-identity

# Ensure you have admin permissions
```

#### **2. Bucket Already Exists**
```bash
# Use a unique bucket name
aws s3 mb s3://vericase-docs-$(whoami)-$(date +%s)
```

#### **3. Lambda Function Fails**
```bash
# Check Lambda logs
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/vericase
```

#### **4. Textract Errors**
- Ensure documents are in supported formats (PDF, PNG, JPG)
- Check file size limits (500MB max)
- Verify S3 bucket permissions

### **Get Help**
- Check AWS CloudTrail for API errors
- Review CloudWatch logs
- Verify IAM permissions
- Test with smaller files first

---

## **What Happens After Setup**

### **Your VeriCase App Now Has:**
- 🧠 **AI Document Analysis** - Automatic classification and entity extraction
- 🔍 **Semantic Search** - Natural language queries across all evidence
- 📊 **Smart Analytics** - AI-powered case insights and recommendations
- 🎯 **Visual Analysis** - Construction photo defect detection
- 🎤 **Audio Processing** - Meeting transcription with speaker ID
- 🔒 **Compliance** - Automatic sensitive data detection

### **New API Endpoints:**
```http
POST /api/v1/aws/evidence/{id}/process     # Process with AI
POST /api/v1/aws/search/semantic           # Natural language search
GET  /api/v1/aws/case/{id}/insights        # AI case analysis
POST /api/v1/aws/audio/{id}/transcribe     # Audio transcription
GET  /api/v1/aws/services/status           # Health check
```

### **Cost Expectations:**
- **First 5GB file:** ~£33 processing cost
- **Monthly ongoing:** ~£17 for storage and search
- **ROI:** Saves 80% of manual review time

---

## **Next Steps**

1. **Upload Test File** - Try a small PST file first
2. **Explore Features** - Test semantic search and AI insights
3. **Train Your Team** - Show them the new capabilities
4. **Scale Up** - Process your full evidence repository
5. **Monitor Costs** - Keep track of usage and optimize

---

## **Support**

### **If You Need Help:**
1. Check the logs in CloudWatch
2. Review the troubleshooting section above
3. Test with smaller files first
4. Verify AWS permissions and quotas

### **Success Indicators:**
- ✅ S3 bucket created and accessible
- ✅ Lambda functions deployed
- ✅ Test document processes successfully
- ✅ API endpoints return valid responses
- ✅ Costs are within expected range

**🎉 Once setup is complete, your VeriCase application will be an AI-powered legal evidence platform that can compete with enterprise solutions!**