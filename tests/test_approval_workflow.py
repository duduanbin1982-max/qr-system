import uuid

import pytest

import modules.services.approval_service as approval_service_module
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.services.approval_service import ApprovalService
from tests.factories import WORKER_HASH, TEST_HASH, create_order, ensure_process, ensure_user


def _make_approval_fixture(client, approval_level=2):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f'Approval Fixture {uuid.uuid4().hex[:8]}', seq_order=991)
        worker_id = ensure_user(
            db,
            f'approval-worker-{uuid.uuid4().hex[:6]}',
            WORKER_HASH,
            'Approval Worker',
            'worker',
            f'AW-{uuid.uuid4().hex[:8].upper()}',
        )
        pm_id = ensure_user(
            db,
            f'approval-pm-{uuid.uuid4().hex[:6]}',
            TEST_HASH,
            'Approval Manager',
            'production_manager',
            f'PM-{uuid.uuid4().hex[:8].upper()}',
        )
        qc_id = ensure_user(
            db,
            f'approval-qc-{uuid.uuid4().hex[:6]}',
            TEST_HASH,
            'Approval QC',
            'qc_inspector',
            f'QC-{uuid.uuid4().hex[:8].upper()}',
        )
        order_id = create_order(db, [process_id], quantity=10, product_code=f'APP-{uuid.uuid4().hex[:8].upper()}')
        db.execute('DELETE FROM approval_config WHERE process_id = ?', (process_id,))
        db.execute(
            'INSERT INTO approval_config (process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level) '
            'VALUES (?, 1, ?, ?, ?, ?)',
            (process_id, 'production_manager', 'qc_inspector' if approval_level >= 2 else '', '', approval_level),
        )
        work_record_id = db.execute(
            'INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no) '
            "VALUES (?, ?, ?, 'normal', 1, '', 'pending', '')",
            (order_id, process_id, worker_id),
        ).lastrowid
        approval_id = db.execute(
            "INSERT INTO approval_records (work_record_id, status, current_level, comment) VALUES (?, 'pending', 1, '')",
            (work_record_id,),
        ).lastrowid
        db.commit()
    return {
        'process_id': process_id,
        'worker_id': worker_id,
        'pm_id': pm_id,
        'qc_id': qc_id,
        'order_id': order_id,
        'work_record_id': work_record_id,
        'approval_id': approval_id,
    }


@pytest.fixture
def approval_writer_stub(monkeypatch):
    applied = {}
    monkeypatch.setattr(
        approval_service_module.WorkReportWriter,
        'apply_approved_normal_report',
        staticmethod(lambda command, db, work_record_id=None: applied.update(
            command=command,
            work_record_id=work_record_id,
        )),
    )
    return applied


def test_approval_config_returns_real_role_options(client, auth_headers):
    response = client.get('/api/approvals/config', headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    role_codes = [row['code'] for row in data['role_options']]
    assert 'admin' in role_codes
    assert 'production_manager' in role_codes
    assert 'worker' not in role_codes
    assert 'qc_inspector' not in role_codes


def test_approval_config_returns_process_id_without_existing_config(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(
            db,
            name=f'Approval Unconfigured {uuid.uuid4().hex[:8]}',
            seq_order=994,
        )
        db.execute('DELETE FROM approval_config WHERE process_id = ?', (process_id,))
        db.commit()

    response = client.get('/api/approvals/config', headers=auth_headers)

    assert response.status_code == 200
    configs = response.get_json()['configs']
    config = next(row for row in configs if row['process_id'] == process_id)
    assert config['process_name'].startswith('Approval Unconfigured')
    assert config['require_approval'] == 0


def test_approval_config_schema_rejects_invalid_level(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f'Approval Schema {uuid.uuid4().hex[:8]}', seq_order=992)
    response = client.post(
        '/api/approvals/config',
        headers=auth_headers,
        json={
            'process_id': process_id,
            'require_approval': 1,
            'approver_role': 'admin',
            'approval_level': 4,
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert '参数校验失败' in body['error']


def test_save_config_normalizes_legacy_supervisor_alias(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f'Approval Save {uuid.uuid4().hex[:8]}', seq_order=993)
    response = client.post(
        '/api/approvals/config',
        headers=auth_headers,
        json={
            'process_id': process_id,
            'require_approval': 1,
            'approver_role': 'supervisor',
            'approver_role_2': '',
            'approver_role_3': '',
            'approval_level': 1,
        },
    )
    assert response.status_code == 200
    with client.application.app_context():
        db = get_db()
        row = db.execute(
            'SELECT approver_role, approver_role_2, approver_role_3, approval_level '
            'FROM approval_config WHERE process_id = ?',
            (process_id,),
        ).fetchone()
    assert row['approver_role'] == 'production_manager'
    assert row['approver_role_2'] == ''
    assert row['approver_role_3'] == ''
    assert row['approval_level'] == 1


def test_handle_approval_enforces_roles_and_records_steps(client, approval_writer_stub):
    fixture = _make_approval_fixture(client, approval_level=2)

    with client.application.app_context():
        with pytest.raises(ConflictError):
            ApprovalService.handle(
                fixture['approval_id'],
                'approve',
                approver={'id': fixture['worker_id'], 'name': 'Approval Worker', 'role': 'worker'},
                comment='wrong role',
            )

    with client.application.app_context():
        db = get_db()
        steps = db.execute(
            'SELECT COUNT(*) FROM approval_steps WHERE approval_record_id = ?',
            (fixture['approval_id'],),
        ).fetchone()[0]
    assert steps == 0

    with client.application.app_context():
        result = ApprovalService.handle(
            fixture['approval_id'],
            'approve',
            approver={'id': fixture['pm_id'], 'name': 'Approval Manager', 'role': 'worker'},
            comment='level one',
        )
    assert result == 'approve'

    with client.application.app_context():
        db = get_db()
        record = db.execute(
            'SELECT status, current_level, processed_at FROM approval_records WHERE id = ?',
            (fixture['approval_id'],),
        ).fetchone()
        assert record['status'] == 'pending'
        assert record['current_level'] == 2
        assert record['processed_at'] is not None
        steps = db.execute(
            'SELECT step_level, approver_role, action FROM approval_steps WHERE approval_record_id = ? ORDER BY id',
            (fixture['approval_id'],),
        ).fetchall()
    assert len(steps) == 1
    assert steps[0]['step_level'] == 1
    assert steps[0]['approver_role'] == 'production_manager'
    assert steps[0]['action'] == 'advance'

    with client.application.app_context():
        result = ApprovalService.handle(
            fixture['approval_id'],
            'approve',
            approver={'id': fixture['qc_id'], 'name': 'Approval QC', 'role': 'qc_inspector'},
            comment='final',
        )
    assert result == 'approve'
    assert approval_writer_stub['work_record_id'] == fixture['work_record_id']
    assert approval_writer_stub['command'].order_id == fixture['order_id']

    with client.application.app_context():
        db = get_db()
        record = db.execute(
            'SELECT status, current_level, processed_at FROM approval_records WHERE id = ?',
            (fixture['approval_id'],),
        ).fetchone()
        work_record = db.execute(
            'SELECT status FROM work_records WHERE id = ?',
            (fixture['work_record_id'],),
        ).fetchone()
        steps = db.execute(
            'SELECT step_level, approver_role, action FROM approval_steps WHERE approval_record_id = ? ORDER BY id',
            (fixture['approval_id'],),
        ).fetchall()
    assert record['status'] == 'approved'
    assert record['current_level'] == 2
    assert record['processed_at'] is not None
    assert work_record['status'] == 'approved'
    assert len(steps) == 2
    assert steps[1]['step_level'] == 2
    assert steps[1]['approver_role'] == 'qc_inspector'
    assert steps[1]['action'] == 'approve'

    with client.application.app_context():
        with pytest.raises(ConflictError):
            ApprovalService.handle(
                fixture['approval_id'],
                'approve',
                approver={'id': fixture['qc_id'], 'name': 'Approval QC', 'role': 'qc_inspector'},
                comment='duplicate',
            )

    with client.application.app_context():
        db = get_db()
        step_count = db.execute(
            'SELECT COUNT(*) FROM approval_steps WHERE approval_record_id = ?',
            (fixture['approval_id'],),
        ).fetchone()[0]
    assert step_count == 2
