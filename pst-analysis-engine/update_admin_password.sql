-- Update admin password with correct pbkdf2-sha256 hash
UPDATE users 
SET password_hash = '$pbkdf2-sha256$29000$bY3RmlNq7f3fG0MoZUzp/Q$uctPh9A.GqXMdsDELsgOFvv/ZNza5iHRTVUhXTw3nKk'
WHERE email = 'admin@vericase.com';

-- Verify update
SELECT email, role, is_active, length(password_hash) as hash_length, 
       substring(password_hash, 1, 20) as hash_preview
FROM users 
WHERE email = 'admin@vericase.com';
