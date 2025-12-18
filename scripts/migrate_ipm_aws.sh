#!/bin/bash
# Run this script on your AWS EC2 instance to migrate IPM items
# Usage: ./migrate_ipm_aws.sh

set -e

echo "=== VeriCase IPM Item Migration ==="
echo ""

# Database credentials from environment or defaults
DB_USER=${DB_USER:-vericase}
DB_PASSWORD=${DB_PASSWORD:-vericase}
DB_HOST=${DB_HOST:-database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com}
DB_NAME=${DB_NAME:-vericase}

echo "Connecting to: $DB_HOST/$DB_NAME"
echo ""

# Count query
COUNT_SQL="SELECT COUNT(*) FROM email_messages 
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');"

echo "Checking for IPM items to hide..."
COUNT=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c "$COUNT_SQL" | xargs)

echo "Found $COUNT items to hide"
echo ""

if [ "$COUNT" -eq "0" ]; then
    echo "✓ No items need to be hidden!"
    exit 0
fi

# Show samples
SAMPLE_SQL="SELECT subject FROM email_messages
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false')
LIMIT 10;"

echo "Sample subjects:"
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "$SAMPLE_SQL"
echo ""

# Confirm
read -p "Proceed with hiding $COUNT items? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Update query
UPDATE_SQL="BEGIN;
UPDATE email_messages
SET metadata = COALESCE(metadata, '{}'::jsonb) || 
    '{\"is_hidden\": true, \"is_spam\": true, \"spam_category\": \"non_email\", \"spam_score\": 100}'::jsonb
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');
COMMIT;"

echo ""
echo "Applying update..."
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "$UPDATE_SQL"

# Verify
VERIFY_SQL="SELECT COUNT(*) FROM email_messages 
WHERE metadata->>'is_hidden' = 'true';"

echo ""
echo "Verifying..."
HIDDEN_COUNT=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c "$VERIFY_SQL" | xargs)

echo "✓ Migration complete!"
echo "✓ Total hidden items: $HIDDEN_COUNT"
