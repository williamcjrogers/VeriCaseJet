-- Show some sample IPM subjects
SELECT subject, metadata, id
FROM email_messages
WHERE subject LIKE 'IPM.%'
LIMIT 10;
