.headers on
.mode box

SELECT user_version FROM pragma_user_version;
SELECT integrity_check FROM pragma_integrity_check;
SELECT COUNT(*) AS foreign_key_violations FROM pragma_foreign_key_check;

SELECT id, name, status
FROM departments
ORDER BY id;

SELECT id, name, status
FROM positions
ORDER BY id;

SELECT id, username, name, employee_no, role, status, department_id, position_id
FROM users
WHERE id IN (10304, 10305, 10333, 10334, 10335)
   OR username IN ('1000_perf', '1004_plan', '1005_reassess')
ORDER BY id;

SELECT u.id AS user_id,
       u.username,
       u.name,
       r.id AS role_id,
       r.code AS role_code,
       r.permissions
FROM users AS u
LEFT JOIN user_roles AS ur ON ur.user_id = u.id
LEFT JOIN roles AS r ON r.id = ur.role_id
WHERE u.id IN (10304, 10305, 10333, 10334, 10335)
ORDER BY u.id, r.id;

SELECT COUNT(*) AS confirmed_assignment_count
FROM performance_assignment_history
WHERE created_by = 10304
  AND source_type IN ('manual_history_confirmation', 'legacy_score_snapshot');

SELECT assignment.id,
       assignment.user_id,
       assignment.employee_name_snapshot,
       assignment.employee_no_snapshot,
       assignment.position_id,
       assignment.position_name_snapshot,
       assignment.department_id,
       assignment.department_name_snapshot,
       assignment.valid_from,
       assignment.valid_to,
       assignment.source_type,
       assignment.source_key
FROM performance_assignment_history AS assignment
WHERE assignment.created_by = 10304
  AND assignment.source_type IN ('manual_history_confirmation', 'legacy_score_snapshot')
ORDER BY assignment.valid_from, assignment.user_id, assignment.id;

SELECT COUNT(*) AS performance_rule_versions FROM performance_rule_versions;
SELECT COUNT(*) AS approved_position_targets
FROM performance_position_target_versions
WHERE status = 'approved';
SELECT COUNT(*) AS assignment_history_count FROM performance_assignment_history;
SELECT COUNT(*) AS legacy_v1_batches FROM performance_batches WHERE version = 1;
SELECT COUNT(*) AS v2_batches FROM performance_batches WHERE version >= 2;
