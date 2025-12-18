SELECT COUNT(*) as items_to_hide
FROM email_messages
WHERE (subject LIKE 'IPM.Activity%' OR subject LIKE 'IPM.Appointment%' 
       OR subject LIKE 'IPM.Task%' OR subject LIKE 'IPM.Contact%'
       OR subject LIKE 'IPM.StickyNote%' OR subject LIKE 'IPM.Schedule%'
       OR subject LIKE 'IPM.DistList%' OR subject LIKE 'IPM.Post%')
AND (metadata IS NULL OR metadata->>'is_hidden' IS NULL OR metadata->>'is_hidden' = 'false');
