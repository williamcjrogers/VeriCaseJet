-- Check count of non-email items to hide
SELECT COUNT(*) as items_to_hide
FROM email_messages
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');

-- Show sample subjects
SELECT subject 
FROM email_messages
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false')
LIMIT 10;

-- UNCOMMENT BELOW TO RUN THE UPDATE:
-- BEGIN;
-- 
-- UPDATE email_messages
-- SET metadata = COALESCE(metadata, '{}'::jsonb) || 
--     '{"is_hidden": true, "is_spam": true, "spam_category": "non_email", "spam_score": 100}'::jsonb
-- WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
--        OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
--        OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
--        OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
-- AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');
-- 
-- -- Verify the changes
-- SELECT COUNT(*) as now_hidden
-- FROM email_messages
-- WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
--        OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
--        OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
--        OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
-- AND metadata->>'is_hidden' = 'true';
-- 
-- COMMIT;
