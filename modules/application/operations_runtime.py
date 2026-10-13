"""Application lifecycle details kept behind the stable operations facade."""
from contextlib import contextmanager
from pathlib import Path


class RuntimeOperations:
    @staticmethod
    def load_environment():
        from modules.bootstrap import load_environment

        return load_environment()

    @staticmethod
    def initialize_database():
        from modules.db import init_db

        return init_db()

    @staticmethod
    def verify_schema():
        from modules.db import verify_schema

        return int(verify_schema())

    @staticmethod
    def canonical_json_v1(value):
        from modules.domain.evidence_protocol import canonical_json_v1

        return canonical_json_v1(value)

    @staticmethod
    def sha256_digest_v1(value):
        from modules.domain.evidence_protocol import sha256_digest_v1

        return sha256_digest_v1(value)

    @staticmethod
    def process_fact_bindings():
        from modules.migration_process_versioning import PROCESS_FACT_BINDINGS
        from .operations_dto import detach_result

        return detach_result(PROCESS_FACT_BINDINGS)

    @staticmethod
    def master_data_references():
        from modules.master_data_references import MASTER_DATA_REFERENCES
        from .operations_dto import MasterDataReference

        return tuple(MasterDataReference(
            item.entity_type, item.table, tuple(item.root_columns),
            tuple(item.version_columns), tuple(item.csv_columns),
        ) for item in MASTER_DATA_REFERENCES)

    @staticmethod
    def find_unregistered_reference_columns(*args, **kwargs):
        from modules.master_data_references import find_unregistered_reference_columns

        return find_unregistered_reference_columns(*args, **kwargs)

    @staticmethod
    def load_price_binding_resolution_manifest():
        from modules.process_v2_price_resolution_manifest import load_price_binding_resolution_manifest

        return load_price_binding_resolution_manifest()

    @staticmethod
    def topology_sha256(*args, **kwargs):
        from modules.process_v2_price_resolution_manifest import topology_sha256

        return topology_sha256(*args, **kwargs)

    @staticmethod
    def permission_catalog():
        from modules.permission_catalog import ACTION_PAGE_MAP, PAGE_RULES, PERMISSION_IMPLICATIONS, SIDEBAR_ITEMS
        from .operations_dto import detach_result

        return detach_result({
            "action_page_map": ACTION_PAGE_MAP, "page_rules": PAGE_RULES,
            "permission_implications": PERMISSION_IMPLICATIONS, "sidebar_items": SIDEBAR_ITEMS,
        })

    @staticmethod
    def all_permission_codes():
        from modules.permission_catalog import ALL_PERMISSION_CODES

        return frozenset(ALL_PERMISSION_CODES)

    @staticmethod
    def insert_audit_log(*args, **kwargs):
        from modules.audit_writer import insert_audit_log

        return insert_audit_log(*args, **kwargs)

    @staticmethod
    def default_database_path(project_root):
        from modules.bootstrap import load_environment

        load_environment(Path(project_root))
        from modules.config import DB_PATH

        return str(DB_PATH)

    @staticmethod
    def run_e2e_server(*, host="127.0.0.1", port=4173):
        from server import app

        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

    @staticmethod
    @contextmanager
    def verification_context(name):
        """Scope verification configuration without exposing a Flask instance."""
        from flask import Flask

        app = Flask(name)
        settings = dict(app.config)
        app.config = settings
        with app.app_context():
            yield settings

    @staticmethod
    @contextmanager
    def application_database():
        from modules.app import app
        from modules.db import get_db

        with app.app_context():
            yield get_db()

    @staticmethod
    def capture_work_fact_binding(db, *, order_id, process_id):
        from modules.process_fact_projection import capture_process_fact_binding

        return capture_process_fact_binding(db, order_id=order_id, process_id=process_id)

    @staticmethod
    def performance_rules():
        from modules.services.performance_scoring_policy import PerformanceScoringPolicy

        return PerformanceScoringPolicy.rules()

    @staticmethod
    def generate_quality_tasks(db, **payload):
        from modules.domain.work_report import WorkReportCommand
        from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService

        command = WorkReportCommand(
            report_type=payload["report_type"], order_id=payload["order_id"],
            process_id=payload["process_id"], user_id=payload["user_id"],
            user_name=payload.get("user_name", ""), serial_no=payload["serial_no"],
            quantity=payload.get("quantity", 1),
        )
        return ProcessQualityEvaluationService.generate_tasks(command, payload["trigger_work_record_id"], db)
