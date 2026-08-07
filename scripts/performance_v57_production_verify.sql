.headers on
.mode box

SELECT user_version FROM pragma_user_version;
SELECT integrity_check FROM pragma_integrity_check;
SELECT COUNT(*) AS foreign_key_violations FROM pragma_foreign_key_check;

SELECT id, name, status
FROM departments
WHERE name = '机加工班组';

SELECT u.id,
       u.username,
       u.name,
       u.status,
       r.code AS role_code,
       r.permissions,
       COUNT(scope.department_id) AS scope_count,
       GROUP_CONCAT(scope.department_id) AS department_ids
FROM users AS u
JOIN user_roles AS ur ON ur.user_id = u.id
JOIN roles AS r ON r.id = ur.role_id
LEFT JOIN performance_department_scopes AS scope ON scope.user_id = u.id
WHERE u.username IN ('1000_perf', '1004_plan', '1005_reassess')
GROUP BY u.id, u.username, u.name, u.status, r.code, r.permissions
ORDER BY u.id;

SELECT COUNT(*) AS approved_department_revisions,
       COUNT(DISTINCT assignment_id) AS assignment_count,
       MIN(created_by) AS min_created_by,
       MAX(created_by) AS max_created_by,
       MIN(approved_by) AS min_approved_by,
       MAX(approved_by) AS max_approved_by
FROM performance_assignment_department_revisions
WHERE status = 'approved'
  AND source_key LIKE 'performance-v57:department-supplement:%';

SELECT COUNT(*) AS original_assignment_department_fields_changed
FROM performance_assignment_history
WHERE created_by = 10304
  AND source_type IN ('manual_history_confirmation', 'legacy_score_snapshot')
  AND (department_id IS NOT NULL OR department_name_snapshot <> '');

SELECT COUNT(*) AS legacy_v1_batches
FROM performance_batches
WHERE version = 1;

SELECT COUNT(*) AS v2_batches
FROM performance_batches
WHERE version >= 2;

SELECT
  (SELECT COUNT(*) FROM payroll_batches) AS payroll_batches,
  (SELECT COUNT(*) FROM payroll_employee_lines) AS payroll_employee_lines,
  (SELECT COUNT(*) FROM payroll_adjustments) AS payroll_adjustments,
  (SELECT COUNT(*) FROM payroll_detail_lines) AS payroll_detail_lines,
  (SELECT COUNT(*) FROM payroll_work_price_resolutions) AS payroll_work_price_resolutions,
  (SELECT COUNT(*) FROM payroll_events) AS payroll_events,
  (SELECT COUNT(*) FROM payroll_migration_manifests) AS payroll_migration_manifests;

SELECT id, user_id, action, target_type, target_id, created_at
FROM audit_logs
WHERE action = 'performance_v57_provisioning'
ORDER BY id DESC
LIMIT 1;
