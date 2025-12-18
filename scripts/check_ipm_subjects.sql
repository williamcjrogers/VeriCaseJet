-- Check for any subjects that start with IPM
SELECT COUNT(*) as total_ipm_subjects
FROM email_messages
WHERE subject LIKE 'IPM.%';
