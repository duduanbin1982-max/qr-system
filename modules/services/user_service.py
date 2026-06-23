"""qr-system - User Service (Repository-pattern refactor)

All business logic (validation, bcrypt, secrets) stays here.
All SQL delegated to UserRepository.
"""
import bcrypt
import secrets
import os
import uuid
from modules.services import BaseService
from modules.repositories.user_repository import UserRepository


class UserService:
    """User management business logic. All methods are static."""

    @staticmethod
    def _validate_process_ids(data):
        """Shared process validation - auto-filter invalid process IDs (self-healing)."""
        if "process_ids" in data and data["process_ids"]:
            id_list = [int(x.strip()) for x in data["process_ids"].split(",") if x.strip()]
            if id_list:
                valid_ids = UserRepository.validate_process_ids(id_list)
                filtered = [str(x) for x in id_list if x in valid_ids]
                data["process_ids"] = ",".join(filtered) if filtered else ""
                data["_valid_process_ids"] = [int(x) for x in filtered] if filtered else []

    # ============================================================
    # Query
    # ============================================================

    @staticmethod
    def list_users(page=1, limit=20, role_filter="", role_not="", keyword="", status=""):
        """Paginated user list."""
        return UserRepository.list_users(
            page=page, limit=limit, role_filter=role_filter,
            role_not=role_not, keyword=keyword, status=status
        )

    # ============================================================
    # Create
    # ============================================================

    @staticmethod
    def create_user(data):
        """Create a new user. Returns (uid, password)."""
        username = data.get("username", "").strip()
        name = data.get("name", "").strip()
        if not name and data.get("role") == "admin":
            name = username
        if not username or not name:
            raise ValueError("Username and name cannot be empty")
        if len(username) < 2 or len(username) > 32:
            raise ValueError("Username must be 2-32 characters")
        if not all(c.isalnum() or c in "_-." for c in username):
            raise ValueError("Username can only contain letters, digits, underscores, hyphens and dots")

        db = BaseService.db()

        # Resolve role from DB (supports custom roles)
        role = data.get("role", "worker")
        role_id = data.get("role_id")
        if not role_id and role:
            role_row = UserRepository.find_role_by_code(role, db=db)
            if not role_row:
                role_row = UserRepository.find_role_by_code("worker", db=db)
            role_id = role_row[0] if role_row else 2
        if not role_id:
            role_id = 2

        # Only admins can create admin users
        if role_id == 1:
            caller_id = data.get("_caller_user_id")
            if not caller_id:
                raise ValueError("Only administrators can create admin accounts")
            if not UserRepository.check_admin_role(caller_id, db=db):
                raise ValueError("Only administrators can create admin accounts")

        # Uniqueness check
        if UserRepository.find_user_by_username(username, db=db):
            raise ValueError("Username already exists")

        # Position validation
        position_id = data.get("position_id")
        if position_id:
            if not UserRepository.find_position_by_id(position_id, db=db):
                raise ValueError("Specified position does not exist")

        # Process validation
        UserService._validate_process_ids(data)

        # Employee number - auto-generate 4-digit if not provided
        employee_no = (data.get("employee_no") or "").strip()
        if not employee_no:
            next_no = UserRepository.get_next_employee_no(db=db)
            employee_no = str(next_no).zfill(4)
            while UserRepository.check_employee_no_exists(employee_no, db=db):
                next_no += 1
                employee_no = str(next_no).zfill(4)
        data["employee_no"] = employee_no

        # Password
        raw_pw = (data.get("password") or "").strip() or secrets.token_urlsafe(8)
        if data.get("password") and len(raw_pw) < 6:
            raise ValueError("Password must be at least 6 characters")
        pw = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

        with BaseService.transaction() as txn:
            uid = UserRepository.insert_user_txn(
                username=username, pw_hash=pw, name=name,
                nickname=data.get("nickname", ""),
                email=data.get("email", ""),
                group_name=data.get("group_name", '员工组'),
                role=role,
                employee_no=data.get("employee_no", ""),
                marker=(data.get("marker") or "").strip(),
                phone=data.get("phone", ""),
                position_id=position_id or None,
                status=data.get("status", "active"),
                db=txn
            )
            UserRepository.insert_user_role_txn(uid, role_id, db=txn)
            # Sync process assignments
            valid_pids = data.get("_valid_process_ids", [])
            if not valid_pids and data.get("process_ids"):
                valid_pids = [int(x.strip()) for x in data["process_ids"].split(",") if x.strip()]
            for pid in valid_pids:
                UserRepository.insert_user_process_txn(uid, pid, db=txn)

        return uid, raw_pw

    # ============================================================
    # Update
    # ============================================================

    @staticmethod
    def update_user(uid, data, current_user_id=None):
        """Update user info."""
        db = BaseService.db()
        existing = UserRepository.find_user_by_id_for_update(uid, db=db)
        if not existing:
            raise ValueError("User not found")

        # Position validation
        if "position_id" in data:
            position_id = data["position_id"]
            if position_id:
                if not UserRepository.find_position_by_id(position_id, db=db):
                    raise ValueError("Specified position does not exist")

        # Process validation
        UserService._validate_process_ids(data)

        old_role = existing["role"]

        # Compute new_role_id
        new_role_id = None
        if ("role" in data and data["role"] != old_role) or ("role_id" in data):
            new_role_id = data.get("role_id")
            if not new_role_id:
                new_role_id = UserRepository.find_role_id_by_code(
                    data.get("role", "worker"), db=db
                )
            gn_row = UserRepository.get_role_group_name(new_role_id, db=db)
            if gn_row:
                data["group_name"] = gn_row[0]

        # Only admins can promote to admin role
        new_role_id_for_check = new_role_id
        if not new_role_id_for_check and "role" in data:
            new_role_id_for_check = UserRepository.find_role_id_by_code(data["role"], db=db)
        old_role_id_for_check = UserRepository.find_role_id_by_code(old_role, db=db)
        if new_role_id_for_check == 1 and old_role_id_for_check != 1:
            if not UserRepository.check_admin_role(current_user_id, db=db):
                raise ValueError("Only administrators can promote users to admin role")

        # Only admins can change roles, cannot change own role
        if new_role_id_for_check is not None and new_role_id_for_check != old_role_id_for_check:
            if current_user_id is None:
                raise ValueError("Only administrators can change roles")
            if current_user_id == uid:
                raise ValueError("Cannot change your own role")
            if not UserRepository.check_admin_role(current_user_id, db=db):
                raise ValueError("Only administrators can change roles")

        sets = []
        params = []
        if "employee_no" in data and not data["employee_no"]:
            del data["employee_no"]
        for field in ["name", "nickname", "email", "group_name", "role", "employee_no",
                       "marker", "phone", "status", "position_id", "department_id"]:
            if field in data:
                sets.append(field + " = ?")
                params.append(data[field])
        if "password" in data and data["password"]:
            sets.append("password = ?")
            params.append(bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt(rounds=12)).decode())
        if not sets:
            raise ValueError("No update fields provided")

        with BaseService.transaction() as txn:
            # Sync process assignments
            if "process_ids" in data or "_valid_process_ids" in data:
                UserRepository.delete_user_processes_txn(uid, db=txn)
                valid_pids = data.get("_valid_process_ids", [])
                if not valid_pids and data.get("process_ids"):
                    valid_pids = [int(x.strip()) for x in data["process_ids"].split(",") if x.strip()]
                for pid in valid_pids:
                    UserRepository.insert_user_process_txn(uid, pid, db=txn)

            UserRepository.update_user_txn(uid, ", ".join(sets), params, db=txn)

            if new_role_id is not None:
                # Prevent downgrading last admin
                if new_role_id != 1:
                    remaining = UserRepository.count_admin_roles_excluding(uid, db=txn)
                    if remaining == 0:
                        remaining2 = UserRepository.count_admin_users_excluding(uid, db=txn)
                        if remaining2 == 0:
                            raise ValueError("Cannot remove the last administrator")
                old_role_id = UserRepository.find_role_id_by_code(old_role, db=txn) or 2
                UserRepository.delete_user_role_txn(uid, old_role_id, db=txn)
                UserRepository.insert_user_role_txn(uid, new_role_id, db=txn)

        # Audit field changes
        try:
            changed = []
            field_labels = {
                "name": "Name", "nickname": "Nickname", "email": "Email", "phone": "Phone",
                "role": "Role", "employee_no": "Employee No", "marker": "Marker", "group_name": "Role Group",
                "position_id": "Position ID", "status": "Status"
            }
            for field, label in field_labels.items():
                old_val = existing[field] if field in existing.keys() else None
                new_val = data.get(field)
                if new_val is not None and str(old_val) != str(new_val):
                    changed.append(label + ": " + str(old_val) + " -> " + str(new_val))
            if "password" in data and data["password"]:
                changed.append("Password: changed")
            if changed:
                detail = "; ".join(changed)
                UserRepository.insert_audit_log_txn(
                    current_user_id, "update_user", "user", uid, detail, db=db
                )
                db.commit()
        except Exception:
            pass

        return True

    # ============================================================
    # Soft Delete / Restore / Permanent Delete
    # ============================================================

    @staticmethod
    def restore_user(uid):
        db = BaseService.db()
        user = UserRepository.find_deleted_user(uid, db=db)
        if not user:
            raise ValueError("User not found or not deleted")
        UserRepository.restore_user_txn(uid, db=db)
        db.commit()
        return True

    @staticmethod
    def permanent_delete_user(uid):
        db = BaseService.db()
        user = UserRepository.find_deleted_user(uid, db=db)
        if not user:
            raise ValueError("Can only permanently delete trashed users")
        with BaseService.transaction() as txn:
            UserRepository.permanent_delete_cascade_txn(uid, db=txn)
        return True

    @staticmethod
    def delete_user(uid, current_user_id):
        """Soft-delete user by setting status='deleted'."""
        if uid == current_user_id:
            raise ValueError("Cannot delete self")

        db = BaseService.db()
        user = UserRepository.find_user_by_id_basic(uid, db=db)
        if not user:
            raise ValueError("User not found")

        # Admin role check via junction table
        if UserRepository.check_admin_role(uid, db=db):
            if UserRepository.count_admin_roles(db=db) <= 1:
                raise ValueError("Cannot delete the last administrator")

        UserRepository.soft_delete_user_txn(uid, db=db)
        db.commit()
        return True

    @staticmethod
    def batch_update_status(ids, status, current_user_id=None):
        """Batch update user status (active/inactive)."""
        if not ids:
            return 0
        if current_user_id and current_user_id in ids:
            raise ValueError("Cannot change own status")
        if status not in ("active", "inactive"):
            raise ValueError("Invalid status")
        db = BaseService.db()
        count = UserRepository.batch_update_status_txn(ids, status, db=db)
        db.commit()
        return count

    @staticmethod
    def batch_delete_users(ids, current_user_id):
        """Soft-delete multiple users."""
        if not ids:
            return 0
        db = BaseService.db()
        if current_user_id in ids:
            raise ValueError("Cannot delete self")
        # Prevent deleting last admin
        admin_count = UserRepository.count_admin_roles_in_ids(ids, db=db)
        if admin_count > 0:
            if UserRepository.count_admin_roles(db=db) <= admin_count:
                raise ValueError("Cannot remove all administrators")
        count = UserRepository.batch_soft_delete_users_txn(ids, db=db)
        db.commit()
        return count

    # ============================================================
    # Password Reset & Unlock
    # ============================================================

    @staticmethod
    def reset_password(uid, password=None):
        """Reset user password with validation and account unlock."""
        new_pw = password if password else secrets.token_urlsafe(8)
        if password:
            if len(password) < 8:
                raise ValueError("Password must be at least 8 characters")
            if not any(c.isalpha() for c in password):
                raise ValueError("Password must contain at least one letter")
            if not any(c.isdigit() for c in password):
                raise ValueError("Password must contain at least one digit")
        hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

        db = BaseService.db()
        existing = UserRepository.find_user_status(uid, db=db)
        if not existing:
            raise ValueError("User not found")
        if existing["status"] != "active":
            raise ValueError("User is disabled, cannot reset password")

        with BaseService.transaction() as txn:
            UserRepository.reset_password_txn(uid, hashed, db=txn)

        return new_pw

    @staticmethod
    def unlock_user(uid):
        """Unlock user (clear brute-force lockout)."""
        db = BaseService.db()
        row = UserRepository.find_user_by_id_basic(uid, db=db)
        if not row:
            raise ValueError("User not found")
        with BaseService.transaction() as txn:
            UserRepository.unlock_user_txn(uid, db=txn)
        return row["username"]

    # ============================================================
    # Batch Import
    # ============================================================

    @staticmethod
    def import_users(filepath):
        """Import users from .xlsx file. Returns {success, skipped, errors}."""
        import openpyxl
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        field_map = {
            "username": "username", "name": "name", "employee_no": "employee_no",
            "phone": "phone", "email": "email", "nickname": "nickname",
            "position_name": "position_name", "role": "role", "password": "password",
            "process_names": "process_names",
        }
        en_map = {k.lower(): k for k in ["username","name","employee_no","phone","email","nickname","position_name","role","password","process_names"]}

        col_map = {}
        for i, h in enumerate(headers):
            if h is None:
                continue
            h_str = str(h).strip()
            if h_str in field_map:
                col_map[i] = field_map[h_str]
            elif h_str.lower() in en_map:
                col_map[i] = en_map[h_str.lower()]

        if not col_map:
            raise ValueError("No valid column headers found")

        db = BaseService.db()
        pos_rows = UserRepository.get_active_positions(db=db)
        pos_map = {r["name"]: r["id"] for r in pos_rows}

        success = 0
        skipped = 0
        errors = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                row_data = {}
                for col_idx, field in col_map.items():
                    val = row[col_idx] if col_idx < len(row) else None
                    row_data[field] = str(val).strip() if val is not None else ""

                username = row_data.get("username", "")
                name = row_data.get("name", "")
                if not username and not name:
                    skipped += 1
                    errors.append("Row " + str(row_idx) + ": empty username and name")
                    continue
                if not username:
                    username = name
                if not name:
                    name = username

                # Check duplicate
                if UserRepository.find_user_by_username(username, db=db):
                    skipped += 1
                    errors.append("Row " + str(row_idx) + ": username " + username + " already exists")
                    continue

                # Resolve position
                pos_name = row_data.get("position_name", "")
                position_id = pos_map.get(pos_name) if pos_name else None

                # Resolve role
                role = row_data.get("role", "worker")
                role_row = UserRepository.find_role_by_code(role, db=db)
                role_id = role_row[0] if role_row else 2

                # Auto employee_no
                employee_no = row_data.get("employee_no", "")
                if not employee_no:
                    next_no = UserRepository.get_next_employee_no(db=db)
                    employee_no = str(next_no).zfill(4)

                # Password
                raw_pw = row_data.get("password", "") or secrets.token_urlsafe(8)
                pw_hash = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

                with BaseService.transaction() as txn:
                    uid = UserRepository.insert_user_import_txn(
                        username=username, pw_hash=pw_hash, name=name,
                        nickname=row_data.get("nickname", ""),
                        email=row_data.get("email", ""),
                        role=role, employee_no=employee_no,
                        phone=row_data.get("phone", ""),
                        position_id=position_id, db=txn
                    )
                    UserRepository.insert_user_role_txn(uid, role_id, db=txn)

                success += 1
            except Exception as e:
                skipped += 1
                errors.append("Row " + str(row_idx) + ": " + str(e)[:80])

        wb.close()
        return {
            "success": success,
            "skipped": skipped,
            "total": success + skipped,
            "errors": errors[:20],
            "error_summary": "; ".join(errors[:5]) if errors else "",
        }

    # ============================================================
    # Helpers
    # ============================================================

    @staticmethod
    def get_user(uid):
        """Get single user (without password)."""
        row = UserRepository.find_user_by_id_full(uid)
        if not row:
            raise ValueError("User not found")
        u = dict(row)
        u.pop("password", None)
        u.pop("token", None)
        return u

    @staticmethod
    def get_user_detail(uid):
        user = UserService.get_user(uid)
        db = BaseService.db()
        user["role_names"] = [row["name"] for row in UserRepository.get_user_role_names(uid, db=db)]
        user["assigned_processes"] = [dict(row) for row in UserRepository.get_user_assigned_processes(uid, db=db)]
        stats = UserRepository.get_user_work_stats(uid, db=db)
        user["work_stats"] = dict(stats) if stats else {}
        return user

    @staticmethod
    def list_user_documents(uid):
        return [dict(row) for row in UserRepository.list_user_documents(uid)]

    @staticmethod
    def upload_user_document(uid, file_storage, doc_type, uploaded_by, upload_dir):
        if not UserRepository.find_user_by_id_basic(uid):
            raise LookupError("User not found")
        os.makedirs(upload_dir, exist_ok=True)
        ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
        safe_name = str(uid) + "_" + uuid.uuid4().hex
        if ext:
            safe_name += "." + ext
        filepath = os.path.join(upload_dir, safe_name)
        file_storage.save(filepath)
        file_size = os.path.getsize(filepath)
        with BaseService.transaction() as txn:
            UserRepository.insert_user_document_txn(
                uid, file_storage.filename, doc_type, safe_name, file_size, uploaded_by, db=txn
            )
        return {"filename": file_storage.filename, "size": file_size}

    @staticmethod
    def get_user_document_file(uid, doc_id, upload_dir):
        doc = UserRepository.find_user_document(uid, doc_id)
        if not doc:
            raise LookupError("Document not found")
        doc = dict(doc)
        filepath = os.path.join(upload_dir, doc["file_path"])
        if not os.path.exists(filepath):
            raise FileNotFoundError("File not found on disk")
        return doc, filepath

    @staticmethod
    def delete_user_document(uid, doc_id, upload_dir):
        doc = UserRepository.find_user_document(uid, doc_id)
        if not doc:
            raise LookupError("Document not found")
        doc = dict(doc)
        filepath = os.path.join(upload_dir, doc["file_path"])
        if os.path.exists(filepath):
            os.remove(filepath)
        with BaseService.transaction() as txn:
            UserRepository.delete_user_document_txn(doc_id, db=txn)
        return doc

