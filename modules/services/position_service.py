"""
qr-system — 岗位管理 Service 层 (Repository pattern)
"""
from modules.services import BaseService
from modules.repositories.position_repository import PositionRepository


class PositionService:

    @staticmethod
    def list_positions(page=1, limit=100):
        total = PositionRepository.count_positions()
        offset = (page - 1) * limit
        rows = PositionRepository.find_positions_paginated(limit, offset)
        pos_ids = [r['id'] for r in rows]
        proc_map = {}
        if pos_ids:
            procs = PositionRepository.find_position_processes(pos_ids)
            for p in procs:
                proc_map.setdefault(p['position_id'], []).append(dict(p))
        result = []
        for r in rows:
            pos = dict(r)
            pos['processes'] = proc_map.get(pos['id'], [])
            result.append(pos)
        return {'positions': result, 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def create_position(data):
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('岗位名称不能为空')
        process_ids = data.get('process_ids', [])
        if process_ids:
            valid = PositionRepository.find_valid_process_ids(process_ids)
            invalid = [str(pid) for pid in process_ids if pid not in valid]
            if invalid:
                raise ValueError('无效工序ID: ' + ', '.join(invalid))
        import sqlite3
        with BaseService.transaction() as txn:
            if PositionRepository.find_position_by_name(name, db=txn):
                raise ValueError('岗位名称【' + name + '】已存在')
            try:
                cur = PositionRepository.insert_position(
                    name, data.get('description', ''), data.get('status', 'active'), db=txn)
            except sqlite3.IntegrityError:
                raise ValueError('岗位名称【' + name + '】已存在')
            pos_id = cur.lastrowid
            for pid in process_ids:
                PositionRepository.insert_position_process(pos_id, pid, db=txn)
            return pos_id

    @staticmethod
    def update_position(pos_id, data):
        pos = PositionRepository.find_position_by_id(pos_id)
        if not pos:
            raise ValueError('岗位不存在')
        if 'name' in data:
            data['name'] = data['name'].strip()
            if not data['name']:
                raise ValueError('岗位名称不能为空')
        if 'process_ids' in data:
            pids = data['process_ids']
            if pids:
                valid = PositionRepository.find_valid_process_ids(pids)
                invalid = [str(pid) for pid in pids if pid not in valid]
                if invalid:
                    raise ValueError('无效工序ID: ' + ', '.join(invalid))

        sets = []
        params = []
        for field in ['name', 'description', 'status']:
            if field in data:
                val = data[field].strip() if isinstance(data[field], str) else data[field]
                sets.append(field + ' = ?')
                params.append(val)
        changed = len(sets) > 0
        if 'process_ids' in data:
            changed = True
        if not changed:
            raise ValueError('无更新内容')

        sets.append('updated_at = datetime("now","localtime")')
        with BaseService.transaction() as txn:
            if 'name' in data:
                dup = PositionRepository.find_position_by_name_excluding(
                    data['name'], pos_id, db=txn)
                if dup:
                    raise ValueError('岗位名称【' + data['name'] + '】已存在')
            if sets:
                PositionRepository.update_position_fields(
                    pos_id, ', '.join(sets), params, db=txn)
            if 'process_ids' in data:
                PositionRepository.delete_position_processes_by_pos(pos_id, db=txn)
                for pid in data['process_ids']:
                    PositionRepository.insert_position_process(pos_id, pid, db=txn)

    @staticmethod
    def check_impact(pos_id):
        pos = PositionRepository.find_position_name_by_id(pos_id)
        if not pos:
            raise ValueError("Position not found")
        users = PositionRepository.count_users_by_position(pos_id)
        return {"position_id": pos_id, "name": pos["name"], "users": users}

    @staticmethod
    def delete_position(pos_id):
        pos = PositionRepository.find_position_by_id(pos_id)
        if not pos:
            raise ValueError('岗位不存在')
        user_count = PositionRepository.count_users_by_position(pos_id)
        if user_count > 0:
            raise ValueError("该岗位下有 " + str(user_count) + " 个用户，请先将用户调岗后再删除")
        with BaseService.transaction() as txn:
            PositionRepository.delete_position_by_id(pos_id, db=txn)
        return pos['name']
