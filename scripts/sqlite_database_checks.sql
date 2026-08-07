.headers off
.mode list

SELECT 'user_version=' || user_version FROM pragma_user_version;
SELECT 'integrity_check=' || integrity_check FROM pragma_integrity_check;
SELECT 'foreign_key_violations=' || COUNT(*) FROM pragma_foreign_key_check;
