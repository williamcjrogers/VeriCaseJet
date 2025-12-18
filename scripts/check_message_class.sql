-- Check message_class column for IPM items
SELECT COUNT(*) as total_with_message_class
FROM email_messages
WHERE message_class IS NOT NULL;

-- Check for IPM in message_class
SELECT COUNT(*) as ipm_in_message_class
FROM email_messages
WHERE message_class LIKE 'IPM.%';

-- Show sample message_class values
SELECT DISTINCT message_class, COUNT(*) as count
FROM email_messages
WHERE message_class LIKE 'IPM.%'
GROUP BY message_class
LIMIT 20;
