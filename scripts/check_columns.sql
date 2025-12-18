-- Check what columns exist in email_messages
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'email_messages' 
AND column_name IN ('meta', 'metadata')
ORDER BY column_name;
