"""Performance/payroll operations adapters; script guards own authorization."""
from .operations_dto import detach_result


class PerformanceOperations:
    @staticmethod
    def collect_permission_codes(*args, **kwargs):
        from modules.access_policy import collect_permission_codes

        return collect_permission_codes(*args, **kwargs)

    @staticmethod
    def payroll_history_analyze(*args, **kwargs):
        from modules.services.payroll_history_migration_service import PayrollHistoryMigrationService

        return detach_result(PayrollHistoryMigrationService.analyze(*args, **kwargs))

    @staticmethod
    def payroll_history_validate_counts(*args, **kwargs):
        from modules.services.payroll_history_migration_service import PayrollHistoryMigrationService

        return detach_result(PayrollHistoryMigrationService.validate_counts(*args, **kwargs))

    @staticmethod
    def payroll_history_apply(*args, **kwargs):
        from modules.services.payroll_history_migration_service import PayrollHistoryMigrationService

        return detach_result(PayrollHistoryMigrationService.apply(*args, **kwargs))

    @staticmethod
    def performance_history_analyze(*args, **kwargs):
        from modules.services.performance_history_migration_service import PerformanceHistoryMigrationService

        return detach_result(PerformanceHistoryMigrationService.analyze(*args, **kwargs))

    @staticmethod
    def performance_history_validate_counts(*args, **kwargs):
        from modules.services.performance_history_migration_service import PerformanceHistoryMigrationService

        return detach_result(PerformanceHistoryMigrationService.validate_counts(*args, **kwargs))

    @staticmethod
    def performance_history_apply(*args, **kwargs):
        from modules.services.performance_history_migration_service import PerformanceHistoryMigrationService

        return detach_result(PerformanceHistoryMigrationService.apply(*args, **kwargs))

    @staticmethod
    def performance_ledger_batch(*args, **kwargs):
        from modules.repositories.performance_ledger_repository import PerformanceLedgerRepository

        return detach_result(PerformanceLedgerRepository.batch(*args, **kwargs))

    @staticmethod
    def performance_workflow_submit_approval(*args, **kwargs):
        from modules.services.performance_ledger_service import PerformanceLedgerService

        return detach_result(PerformanceLedgerService.submit_approval(*args, **kwargs))

    @staticmethod
    def performance_workflow_approve_batch(*args, **kwargs):
        from modules.services.performance_ledger_service import PerformanceLedgerService

        return detach_result(PerformanceLedgerService.approve_batch(*args, **kwargs))

    @staticmethod
    def performance_list_scores(*args, **kwargs):
        from modules.services.performance_service import PerformanceService

        return detach_result(PerformanceService.list_scores(*args, **kwargs))

    @staticmethod
    def performance_workflow_check_batch_integrity(*args, **kwargs):
        from modules.services.performance_ledger_service import PerformanceLedgerService

        return detach_result(PerformanceLedgerService.check_batch_integrity(*args, **kwargs))

    @staticmethod
    def performance_history_facts_payroll_fingerprint(*args, **kwargs):
        from modules.repositories.performance_history_migration_repository import PerformanceHistoryMigrationRepository

        return detach_result(PerformanceHistoryMigrationRepository.payroll_fingerprint(*args, **kwargs))

    @staticmethod
    def performance_ledger_latest_score_revisions(*args, **kwargs):
        from modules.repositories.performance_ledger_repository import PerformanceLedgerRepository

        return detach_result(PerformanceLedgerRepository.latest_score_revisions(*args, **kwargs))

    @staticmethod
    def performance_workflow_submit_supervisor_review(*args, **kwargs):
        from modules.services.performance_ledger_service import PerformanceLedgerService

        return detach_result(PerformanceLedgerService.submit_supervisor_review(*args, **kwargs))

    @staticmethod
    def performance_workflow_save_supervisor_review(*args, **kwargs):
        from modules.services.performance_ledger_service import PerformanceLedgerService

        return detach_result(PerformanceLedgerService.save_supervisor_review(*args, **kwargs))

    @staticmethod
    def assignment_department_revision_by_source_key(*args, **kwargs):
        from modules.repositories.performance_assignment_department_repository import PerformanceAssignmentDepartmentRepository

        return detach_result(PerformanceAssignmentDepartmentRepository.revision_by_source_key(*args, **kwargs))

    @staticmethod
    def assignment_department_workflow_create_revision(*args, **kwargs):
        from modules.services.performance_assignment_department_service import PerformanceAssignmentDepartmentService

        return detach_result(PerformanceAssignmentDepartmentService.create_revision(*args, **kwargs))

    @staticmethod
    def assignment_department_workflow_approve_revision(*args, **kwargs):
        from modules.services.performance_assignment_department_service import PerformanceAssignmentDepartmentService

        return detach_result(PerformanceAssignmentDepartmentService.approve_revision(*args, **kwargs))

    @staticmethod
    def access_get_permission_rows(*args, **kwargs):
        from modules.repositories.access_policy_repository import AccessPolicyRepository

        return detach_result(AccessPolicyRepository.get_permission_rows(*args, **kwargs))

    @staticmethod
    def performance_authorization_can_review_member(*args, **kwargs):
        from modules.services.performance_authorization_service import PerformanceAuthorizationService

        return detach_result(PerformanceAuthorizationService.can_review_member(*args, **kwargs))

    @staticmethod
    def performance_authorization_require_department_action_scope(*args, **kwargs):
        from modules.services.performance_authorization_service import PerformanceAuthorizationService

        return detach_result(PerformanceAuthorizationService.require_department_action_scope(*args, **kwargs))

    @staticmethod
    def performance_improvement_create_plan(*args, **kwargs):
        from modules.services.performance_improvement_service import PerformanceImprovementService

        return detach_result(PerformanceImprovementService.create_plan(*args, **kwargs))

    @staticmethod
    def performance_improvement_transition(*args, **kwargs):
        from modules.services.performance_improvement_service import PerformanceImprovementService

        return detach_result(PerformanceImprovementService.transition(*args, **kwargs))

    @staticmethod
    def performance_improvement_add_evidence(*args, **kwargs):
        from modules.services.performance_improvement_service import PerformanceImprovementService

        return detach_result(PerformanceImprovementService.add_evidence(*args, **kwargs))

    @staticmethod
    def performance_improvement_reassess(*args, **kwargs):
        from modules.services.performance_improvement_service import PerformanceImprovementService

        return detach_result(PerformanceImprovementService.reassess(*args, **kwargs))

    @staticmethod
    def performance_results_formal_result_batch(*args, **kwargs):
        from modules.repositories.performance_repository import PerformanceRepository

        return detach_result(PerformanceRepository.formal_result_batch(*args, **kwargs))

    @staticmethod
    def payroll_workflow_create_batch(*args, **kwargs):
        from modules.services.payroll_service import PayrollWorkflowService

        return detach_result(PayrollWorkflowService.create_batch(*args, **kwargs))

    @staticmethod
    def performance_assignment_assignment_at(*args, **kwargs):
        from modules.repositories.performance_assignment_repository import PerformanceAssignmentRepository

        return detach_result(PerformanceAssignmentRepository.assignment_at(*args, **kwargs))

    @staticmethod
    def get_permission_rows(*args, **kwargs):
        return PerformanceOperations.access_get_permission_rows(*args, **kwargs)

    @staticmethod
    def analyze(*args, **kwargs):
        return PerformanceOperations.performance_history_analyze(*args, **kwargs)

    @staticmethod
    def validate_counts(*args, **kwargs):
        return PerformanceOperations.performance_history_validate_counts(*args, **kwargs)

    @staticmethod
    def assignment_at(*args, **kwargs):
        return PerformanceOperations.performance_assignment_assignment_at(*args, **kwargs)
