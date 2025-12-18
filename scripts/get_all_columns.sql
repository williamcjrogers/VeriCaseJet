-- Get all column names from email_messages
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'email_messages' 
ORDER BY ordinal_position;
