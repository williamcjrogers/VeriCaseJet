-- Check total email count
SELECT COUNT(*) as total_emails FROM email_messages;

-- Check subjects that contain IPM anywhere (not just at start)
SELECT COUNT(*) as ipm_anywhere 
FROM email_messages 
WHERE subject ILIKE '%IPM.%';

-- Show sample subjects to understand the data
SELECT subject 
FROM email_messages 
WHERE subject IS NOT NULL
LIMIT 20;
