# Fix PST Upload - Database Column Too Small

## Problem
The `Bobby.Kher@UnitedLiving.co.uk.001.pst` file failed because:
- An attachment filename `00.00_Welbourne_-_Ventilation_to_Block_A_Block_B_Lobby_to_Car_Park` has no file extension
- The code treated everything after the first dot as the "extension"
- This resulted in a 65-character "extension" being inserted into a VARCHAR(50) column

## Solution Applied (Code)
1. ✅ Updated `pst_processor.py` to truncate extensions to 255 chars
2. ✅ Updated `evidence_repository.py` with flexible `get_file_type()`
3. ✅ Updated `models.py` to use VARCHAR(255) for `file_type` and `mime_type`
4. ✅ Added AG Grid flexible column handling

## Database Migration Required

**SSH into the EC2 server and run:**

```bash
# Connect to EC2
ssh -i ~/.ssh/vericase-key.pem ec2-user@18.130.216.34

# Run the migration
docker exec -i $(docker ps -qf "name=db") psql -U vericase -d vericase << 'EOF'
-- Increase file_type from VARCHAR(50) to VARCHAR(255)
ALTER TABLE evidence_items ALTER COLUMN file_type TYPE VARCHAR(255);

-- Increase mime_type from VARCHAR(128) to VARCHAR(255)
ALTER TABLE evidence_items ALTER COLUMN mime_type TYPE VARCHAR(255);

-- Verify the change
SELECT column_name, data_type, character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'evidence_items' 
AND column_name IN ('file_type', 'mime_type');
EOF
```

## Redeploy the Application

```bash
# Pull latest code changes
cd /home/ec2-user/vericase
git pull origin main

# Rebuild and restart containers
docker-compose -f docker-compose-s3.yml pull
docker-compose -f docker-compose-s3.yml up -d

# Or if using pre-built images:
docker pull wcjrogers/vericase-api:latest
docker-compose -f docker-compose-s3.yml up -d --force-recreate api worker
```

## Reprocess the Failed PST

After the migration and redeploy, reprocess the failed PST:

```bash
curl -X POST "http://18.130.216.34:8010/api/correspondence/pst/PST_FILE_ID/process"
```

Or simply re-upload the file through the UI.

## Verify Fix

```bash
# Check PST status
curl -s "http://18.130.216.34:8010/api/correspondence/pst/files" | jq '.items[0]'
```

