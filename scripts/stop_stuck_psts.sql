-- Stop all failed or stuck PST processing tasks
-- This script identifies and stops PSTs that are:
--   1. Stuck in 'processing' status for >2 hours
--   2. Stuck in 'pending' status for >2 hours (uploaded but never started)
--   3. Already marked as 'failed' (for reporting)

-- First, let's see what we have
SELECT 
    'CURRENT STATUS' as report_type,
    processing_status,
    COUNT(*) as count,
    SUM(CASE WHEN processing_status IN ('processing', 'pending') AND 
        (processing_started_at < NOW() - INTERVAL '2 hours' OR 
         (processing_started_at IS NULL AND uploaded_at < NOW() - INTERVAL '2 hours')) 
        THEN 1 ELSE 0 END) as stuck_count
FROM pst_files
GROUP BY processing_status
ORDER BY processing_status;

-- Show details of stuck PSTs
SELECT 
    'STUCK PST DETAILS' as report_type,
    id,
    filename,
    processing_status,
    uploaded_at,
    processing_started_at,
    processing_completed_at,
    total_emails,
    processed_emails,
    LEFT(error_message, 100) as error_preview,
    CASE 
        WHEN processing_started_at IS NOT NULL 
        THEN EXTRACT(EPOCH FROM (NOW() - processing_started_at))/3600
        WHEN uploaded_at IS NOT NULL
        THEN EXTRACT(EPOCH FROM (NOW() - uploaded_at))/3600
        ELSE NULL
    END as hours_stuck
FROM pst_files
WHERE processing_status IN ('processing', 'pending')
    AND (
        processing_started_at < NOW() - INTERVAL '2 hours' 
        OR (processing_started_at IS NULL AND uploaded_at < NOW() - INTERVAL '2 hours')
    )
ORDER BY uploaded_at DESC;

-- ** UNCOMMENT THE SECTION BELOW TO ACTUALLY STOP THE STUCK PSTs **
/*
-- Update stuck PSTs to 'failed' status
UPDATE pst_files
SET 
    processing_status = 'failed',
    processing_completed_at = COALESCE(processing_completed_at, NOW()),
    error_message = CASE 
        WHEN error_message IS NULL THEN 
            'Stopped by admin at ' || NOW()::text || ' - stuck in ''' || processing_status || ''' status for >2h'
        ELSE 
            error_message || E'\n' || 'Stopped by admin at ' || NOW()::text || ' - stuck in ''' || processing_status || ''' status for >2h'
    END
WHERE processing_status IN ('processing', 'pending')
    AND (
        processing_started_at < NOW() - INTERVAL '2 hours' 
        OR (processing_started_at IS NULL AND uploaded_at < NOW() - INTERVAL '2 hours')
    );

-- Show the update results
SELECT 
    'UPDATE COMPLETE' as report_type,
    COUNT(*) as stopped_count
FROM pst_files
WHERE processing_status = 'failed'
    AND error_message LIKE '%Stopped by admin%';
*/

-- Final status summary
SELECT 
    'FINAL STATUS' as report_type,
    processing_status,
    COUNT(*) as count
FROM pst_files
GROUP BY processing_status
ORDER BY processing_status;
