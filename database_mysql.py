import pandas as pd
from sqlalchemy import create_engine, text
import streamlit as st
import os
import logging

logger = logging.getLogger("eims_db")
logger.setLevel(logging.WARNING)



class Database:

    def add_security_event(self, email, event_type, description=''):
        """سجل حدث أمني (مثل محاولة دخول فاشلة) في جدول it_security_events"""
        sql = text('''
            INSERT INTO it_security_events (email, event_type, description, timestamp)
            VALUES (:email, :event_type, :description, NOW())
        ''')
        try:
            with self.get_connection() as conn:
                conn.execute(sql, {'email': email, 'event_type': event_type, 'description': description})
                try:
                    conn.commit()
                except Exception:
                    pass
        except Exception as e:
            logger.exception(f"Failed to add security event: {e}")
            return False
        return True

    _engine = None

    def get_latest_performance_monitoring(self):
        """جلب آخر بيانات مراقبة الأداء من جدول it_performance_monitoring"""
        try:
            sql = text("SELECT * FROM it_performance_monitoring ORDER BY timestamp DESC LIMIT 1")
            with self.get_connection() as conn:
                result = conn.execute(sql)
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.exception("Failed to fetch performance monitoring data")
            return None

    def get_latest_server_status(self):
        """جلب آخر حالة لكل سيرفر — يحسب Online/Offline بناءً على آخر تحديث (5 دقائق)"""
        try:
            sql = text("SELECT * FROM it_servers_status ORDER BY timestamp DESC")
            with self.get_connection() as conn:
                df = pd.read_sql(sql, conn)
                if not df.empty:
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                    df = df.sort_values('timestamp').drop_duplicates('server_name', keep='last')
                    now = pd.Timestamp.now()
                    df['is_online'] = (now - df['timestamp']).dt.total_seconds() < 300  # 5 دقائق
                    df['status'] = df['is_online'].map({True: 'Online', False: 'Offline'})
                    df['last_seen_seconds'] = (now - df['timestamp']).dt.total_seconds().astype(int)
                    return df.to_dict(orient='records')
                return []
        except Exception as e:
            logger.exception("Failed to fetch server status data")
            return []

    def get_user_activity_log(self, user_email, limit=50):
        try:
            sql = text("""
                SELECT
                    COALESCE(event_type, action, '') AS event_type,
                    COALESCE(description, details, '') AS description,
                    timestamp
                FROM it_activity_log
                WHERE LOWER(COALESCE(user_email,'')) = LOWER(:email)
                ORDER BY timestamp DESC
                LIMIT :lim
            """)
            return self.fetch_dataframe(sql, {"email": user_email, "lim": limit})
        except Exception:
            logger.exception("Failed to fetch user activity log")
            return pd.DataFrame()

    def get_recent_activity_log(self, limit=10):
        """جلب آخر الأنشطة من كلا الجدولين مع دعم البنيتين القديمة والجديدة"""
        try:
            sql = text("""
                SELECT
                    COALESCE(user_email, '') AS user_email,
                    COALESCE(event_type, action, '') AS event_type,
                    COALESCE(description, details, '') AS description,
                    timestamp
                FROM it_activity_log
                UNION ALL
                SELECT
                    COALESCE(email, '') AS user_email,
                    event_type,
                    COALESCE(description, '') AS description,
                    timestamp
                FROM it_security_events
                ORDER BY timestamp DESC
                LIMIT :limit
            """)
            with self.get_connection() as conn:
                result = conn.execute(sql, {"limit": limit})
                return [dict(row._mapping) for row in result.fetchall()]
        except Exception:
            logger.exception("Failed to fetch activity log data")
            return []

    def init_support_tickets_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            status VARCHAR(50) DEFAULT 'Open',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass

    def init_it_security_events_table(self):
        with self.get_connection() as conn:
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS it_security_events (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    event_type VARCHAR(100) NOT NULL,
                    description TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            '''))
            # إضافة الأعمدة الناقصة إذا لم تكن موجودة
            for alter_sql in [
                "ALTER TABLE it_security_events ADD COLUMN email VARCHAR(255)",
                "ALTER TABLE it_security_events ADD COLUMN ip_address VARCHAR(50)",
            ]:
                try:
                    conn.execute(text(alter_sql))
                except Exception:
                    pass  # العمود موجود مسبقاً
            try:
                conn.commit()
            except Exception:
                pass

    def init_it_performance_monitoring_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS it_performance_monitoring (
            id INT PRIMARY KEY AUTO_INCREMENT,
            cpu FLOAT DEFAULT 0,
            ram FLOAT DEFAULT 0,
            disk FLOAT DEFAULT 0,
            network_sent FLOAT DEFAULT 0,
            network_recv FLOAT DEFAULT 0,
            response_time FLOAT DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass

    def init_it_servers_status_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS it_servers_status (
            id INT PRIMARY KEY AUTO_INCREMENT,
            server_name VARCHAR(100) NOT NULL,
            status VARCHAR(20) DEFAULT 'Online',
            cpu FLOAT DEFAULT 0,
            ram FLOAT DEFAULT 0,
            disk FLOAT DEFAULT 0,
            uptime_seconds BIGINT DEFAULT 0,
            ip_address VARCHAR(50),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass

    def init_it_activity_log_table(self):
        with self.get_connection() as conn:
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS it_activity_log (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    event_type VARCHAR(100) NOT NULL,
                    description TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
            '''))
            # إضافة الأعمدة الناقصة إذا لم تكن موجودة
            for alter_sql in [
                "ALTER TABLE it_activity_log ADD COLUMN user_email VARCHAR(255)",
                "ALTER TABLE it_activity_log MODIFY COLUMN user_id INT NULL",
            ]:
                try:
                    conn.execute(text(alter_sql))
                except Exception:
                    pass  # العمود موجود أو لا يمكن تعديله
            try:
                conn.commit()
            except Exception:
                pass

    def insert_performance_snapshot(self, cpu, ram, disk, network_sent, network_recv, response_time):
        try:
            sql = text('''
                INSERT INTO it_performance_monitoring
                    (cpu, ram, io, network, disk, network_sent, network_recv, response_time, timestamp)
                VALUES
                    (:cpu, :ram, 0, :network, :disk, :network_sent, :network_recv, :response_time, NOW())
            ''')
            with self.get_connection() as conn:
                conn.execute(sql, {
                    'cpu': cpu, 'ram': ram, 'disk': disk,
                    'network': network_recv,
                    'network_sent': network_sent, 'network_recv': network_recv,
                    'response_time': response_time
                })
                try:
                    conn.commit()
                except Exception:
                    pass
            return True
        except Exception:
            logger.exception("Failed to insert performance snapshot")
            return False

    def insert_server_snapshot(self, server_name, status, cpu, ram, disk, uptime_seconds, ip_address=''):
        try:
            sql = text('''
                INSERT INTO it_servers_status (server_name, status, cpu, ram, disk, uptime_seconds, ip_address, timestamp)
                VALUES (:server_name, :status, :cpu, :ram, :disk, :uptime_seconds, :ip_address, NOW())
            ''')
            with self.get_connection() as conn:
                conn.execute(sql, {
                    'server_name': server_name, 'status': status, 'cpu': cpu,
                    'ram': ram, 'disk': disk, 'uptime_seconds': uptime_seconds,
                    'ip_address': ip_address
                })
                try:
                    conn.commit()
                except Exception:
                    pass
            return True
        except Exception:
            logger.exception("Failed to insert server snapshot")
            return False

    def insert_activity_log(self, event_type, description, user_email=''):
        try:
            # يدعم كلا البنيتين: القديمة (action/details) والجديدة (event_type/description/user_email)
            sql = text('''
                INSERT INTO it_activity_log (action, details, user_email, event_type, description, timestamp)
                VALUES (:action, :details, :user_email, :event_type, :description, NOW())
            ''')
            with self.get_connection() as conn:
                try:
                    conn.execute(sql, {
                        'action': event_type, 'details': description,
                        'user_email': user_email, 'event_type': event_type, 'description': description
                    })
                except Exception:
                    # fallback: بنية قديمة بدون user_email/event_type/description
                    conn.execute(
                        text("INSERT INTO it_activity_log (action, details, timestamp) VALUES (:action, :details, NOW())"),
                        {'action': event_type, 'details': f"{user_email}: {description}"}
                    )
                try:
                    conn.commit()
                except Exception:
                    pass
            return True
        except Exception:
            logger.exception("Failed to insert activity log")
            return False

    def update_ticket_status(self, ticket_id, new_status):
        try:
            sql = text("UPDATE support_tickets SET status=:status WHERE id=:id")
            with self.get_connection() as conn:
                conn.execute(sql, {'status': new_status, 'id': ticket_id})
                try:
                    conn.commit()
                except Exception:
                    pass
            return True
        except Exception:
            logger.exception("Failed to update ticket status")
            return False

    def delete_ticket(self, ticket_id):
        try:
            sql = text("DELETE FROM support_tickets WHERE id=:id")
            with self.get_connection() as conn:
                conn.execute(sql, {'id': ticket_id})
                try:
                    conn.commit()
                except Exception:
                    pass
            return True
        except Exception:
            logger.exception("Failed to delete ticket")
            return False

    def get_all_security_events(self, limit=100):
        try:
            sql = text("SELECT * FROM it_security_events ORDER BY timestamp DESC LIMIT :limit")
            with self.get_connection() as conn:
                result = conn.execute(sql, {'limit': limit})
                return [dict(row._mapping) for row in result.fetchall()]
        except Exception:
            logger.exception("Failed to fetch security events")
            return []

    def get_performance_history(self, limit=20):
        try:
            sql = text("SELECT * FROM it_performance_monitoring ORDER BY timestamp DESC LIMIT :limit")
            with self.get_connection() as conn:
                result = conn.execute(sql, {'limit': limit})
                rows = [dict(row._mapping) for row in result.fetchall()]
                return list(reversed(rows))
        except Exception:
            logger.exception("Failed to fetch performance history")
            return []

    def init_users_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS users (
            id INT PRIMARY KEY AUTO_INCREMENT,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            salt VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'employee',
            full_name VARCHAR(255) DEFAULT '',
            phone VARCHAR(64) DEFAULT '',
            avatar VARCHAR(512) DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # migrate older schemas
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users'"))
                existing = {r[0].lower() for r in res.fetchall()}
                for col, ddl in {
                    'full_name': "ALTER TABLE users ADD COLUMN full_name VARCHAR(255) DEFAULT ''",
                    'phone':     "ALTER TABLE users ADD COLUMN phone VARCHAR(64) DEFAULT ''",
                    'avatar':    "ALTER TABLE users ADD COLUMN avatar VARCHAR(512) DEFAULT ''"
                }.items():
                    if col not in existing:
                        try:
                            conn.execute(text(ddl))
                        except Exception:
                            pass
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                pass

    def init_records_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS company_records (
            id INT PRIMARY KEY AUTO_INCREMENT,
            employee_name VARCHAR(255) NOT NULL,
            department VARCHAR(255),
            position VARCHAR(255),
            salary DOUBLE,
            hire_date DATE,
            email VARCHAR(255),
            phone VARCHAR(64),
            status VARCHAR(64) DEFAULT 'Active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass

    def init_leave_table(self):
        # minimal leave table to satisfy init calls
        sql = text('''
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            start_date DATE,
            end_date DATE,
            reason TEXT,
            leave_type VARCHAR(100),
            attachment VARCHAR(512),
            status VARCHAR(50) DEFAULT 'Pending',
            priority VARCHAR(20) DEFAULT 'Medium',
            manager_response TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # Ensure table has expected columns (in case an older schema exists)
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leave_requests'"))
                cols = {r[0].lower() for r in res.fetchall()}
                expected = {
                    'user_id': "ALTER TABLE leave_requests ADD COLUMN user_id INT NOT NULL",
                    'start_date': "ALTER TABLE leave_requests ADD COLUMN start_date DATE",
                    'end_date': "ALTER TABLE leave_requests ADD COLUMN end_date DATE",
                    'reason': "ALTER TABLE leave_requests ADD COLUMN reason TEXT",
                    'leave_type': "ALTER TABLE leave_requests ADD COLUMN leave_type VARCHAR(100)",
                    'attachment': "ALTER TABLE leave_requests ADD COLUMN attachment VARCHAR(512)",
                    'status': "ALTER TABLE leave_requests ADD COLUMN status VARCHAR(50) DEFAULT 'Pending'",
                    'priority': "ALTER TABLE leave_requests ADD COLUMN priority VARCHAR(20) DEFAULT 'Medium'",
                    'manager_response': "ALTER TABLE leave_requests ADD COLUMN manager_response TEXT",
                    'created_at': "ALTER TABLE leave_requests ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                }
                for col, alter in expected.items():
                    if col not in cols:
                        try:
                            conn.execute(text(alter))
                        except Exception:
                            logger.exception(f"Failed to add column {col} to leave_requests")
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to verify leave_requests schema")

    def init_shipments_table(self):
        # placeholder minimal table
        sql = text('''
        CREATE TABLE IF NOT EXISTS shipments (
            id INT PRIMARY KEY AUTO_INCREMENT,
            shipment_number VARCHAR(255),
            UNIQUE KEY uq_shipment_number (shipment_number),
            client_id INT,
            shipment_type VARCHAR(100),
            origin VARCHAR(255),
            destination VARCHAR(255),
            departure_date DATE,
            expected_arrival DATE,
            total_weight DOUBLE,
            total_value DOUBLE,
            currency VARCHAR(16),
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # Ensure table has expected columns (in case an older schema exists)
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'shipments'"))
                cols = {r[0].lower() for r in res.fetchall()}
                expected = {
                    'shipment_type': "ALTER TABLE shipments ADD COLUMN shipment_type VARCHAR(100)",
                    'origin': "ALTER TABLE shipments ADD COLUMN origin VARCHAR(255)",
                    'destination': "ALTER TABLE shipments ADD COLUMN destination VARCHAR(255)",
                    'departure_date': "ALTER TABLE shipments ADD COLUMN departure_date DATE",
                    'expected_arrival': "ALTER TABLE shipments ADD COLUMN expected_arrival DATE",
                    'total_weight': "ALTER TABLE shipments ADD COLUMN total_weight DOUBLE",
                    'total_value': "ALTER TABLE shipments ADD COLUMN total_value DOUBLE",
                    'currency': "ALTER TABLE shipments ADD COLUMN currency VARCHAR(16)",
                    'notes': "ALTER TABLE shipments ADD COLUMN notes TEXT",
                    'status': "ALTER TABLE shipments ADD COLUMN status VARCHAR(64) DEFAULT 'Pending'",
                    'actual_arrival': "ALTER TABLE shipments ADD COLUMN actual_arrival DATE",
                    'customs_cleared': "ALTER TABLE shipments ADD COLUMN customs_cleared TINYINT(1) DEFAULT 0",
                    'created_at': "ALTER TABLE shipments ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                }
                for col, alter in expected.items():
                    if col not in cols:
                        try:
                            conn.execute(text(alter))
                        except Exception:
                            # ignore individual alter failures
                            logger.exception(f"Failed to add column {col} to shipments")
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to verify shipments schema")

    def init_cargo_items_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS cargo_items (
            id INT PRIMARY KEY AUTO_INCREMENT,
            shipment_id INT,
            item_name VARCHAR(255),
            description TEXT,
            quantity INT,
            unit VARCHAR(32),
            weight DOUBLE,
            value DOUBLE,
            hs_code VARCHAR(64),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # Ensure table has expected columns (for older schemas)
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cargo_items'"))
                cols = {r[0].lower() for r in res.fetchall()}
                expected = {
                    'shipment_id': "ALTER TABLE cargo_items ADD COLUMN shipment_id INT",
                    'item_name': "ALTER TABLE cargo_items ADD COLUMN item_name VARCHAR(255)",
                    'description': "ALTER TABLE cargo_items ADD COLUMN description TEXT",
                    'quantity': "ALTER TABLE cargo_items ADD COLUMN quantity INT",
                    'unit': "ALTER TABLE cargo_items ADD COLUMN unit VARCHAR(32)",
                    'weight': "ALTER TABLE cargo_items ADD COLUMN weight DOUBLE",
                    'value': "ALTER TABLE cargo_items ADD COLUMN value DOUBLE",
                    'hs_code': "ALTER TABLE cargo_items ADD COLUMN hs_code VARCHAR(64)",
                    'created_at': "ALTER TABLE cargo_items ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                }
                for col, alter in expected.items():
                    if col not in cols:
                        try:
                            conn.execute(text(alter))
                        except Exception:
                            logger.exception(f"Failed to add column {col} to cargo_items")
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to verify cargo_items schema")

    def init_tracking_updates_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS tracking_updates (
            id INT PRIMARY KEY AUTO_INCREMENT,
            shipment_id INT,
            location VARCHAR(255),
            status VARCHAR(255),
            notes TEXT,
            updated_by INT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # Ensure table has expected columns (for older schemas)
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_updates'"))
                cols = {r[0].lower() for r in res.fetchall()}
                expected = {
                    'shipment_id': "ALTER TABLE tracking_updates ADD COLUMN shipment_id INT",
                    'location': "ALTER TABLE tracking_updates ADD COLUMN location VARCHAR(255)",
                    'status': "ALTER TABLE tracking_updates ADD COLUMN status VARCHAR(255)",
                    'notes': "ALTER TABLE tracking_updates ADD COLUMN notes TEXT",
                    'updated_by': "ALTER TABLE tracking_updates ADD COLUMN updated_by INT",
                    'created_at': "ALTER TABLE tracking_updates ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                }
                for col, alter in expected.items():
                    if col not in cols:
                        try:
                            conn.execute(text(alter))
                        except Exception:
                            logger.exception(f"Failed to add column {col} to tracking_updates")
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to verify tracking_updates schema")

    def init_documents_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS documents (
            id INT PRIMARY KEY AUTO_INCREMENT,
            shipment_id INT,
            doc_type VARCHAR(255),
            file_path VARCHAR(1024),
            uploaded_by INT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # Ensure table has expected columns (in case an older schema exists)
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents'"))
                cols = {r[0].lower() for r in res.fetchall()}
                expected = {
                    'shipment_id': "ALTER TABLE documents ADD COLUMN shipment_id INT",
                    'doc_type': "ALTER TABLE documents ADD COLUMN doc_type VARCHAR(255)",
                    'file_path': "ALTER TABLE documents ADD COLUMN file_path VARCHAR(1024)",
                    'uploaded_by': "ALTER TABLE documents ADD COLUMN uploaded_by INT",
                    'notes': "ALTER TABLE documents ADD COLUMN notes TEXT",
                    'created_at': "ALTER TABLE documents ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                }
                for col, alter in expected.items():
                    if col not in cols:
                        try:
                            conn.execute(text(alter))
                        except Exception:
                            logger.exception(f"Failed to add column {col} to documents")
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to verify documents schema")

    def init_cargo_requests_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS cargo_requests (
            id INT PRIMARY KEY AUTO_INCREMENT,
            cargo_item_id INT,
            user_id INT,
            request_type VARCHAR(255),
            reason TEXT,
            status VARCHAR(50) DEFAULT 'Pending',
            response TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass

    def init_messages_table(self):
        sql = text('''
        CREATE TABLE IF NOT EXISTS messages (
            id INT PRIMARY KEY AUTO_INCREMENT,
            from_user INT,
            to_user INT,
            subject VARCHAR(255),
            content TEXT,
            shipment_id INT,
            read_flag BOOLEAN DEFAULT FALSE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        ''')
        with self.get_connection() as conn:
            conn.execute(sql)
            try:
                conn.commit()
            except Exception:
                pass
            # verify columns and add missing ones if table existed with older schema
            try:
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'messages'"))
                cols = {r[0].lower() for r in res.fetchall()}
                expected = {
                    'from_user': "ALTER TABLE messages ADD COLUMN from_user INT",
                    'to_user': "ALTER TABLE messages ADD COLUMN to_user INT",
                    'subject': "ALTER TABLE messages ADD COLUMN subject VARCHAR(255)",
                    'content': "ALTER TABLE messages ADD COLUMN content TEXT",
                    'shipment_id': "ALTER TABLE messages ADD COLUMN shipment_id INT",
                    'read_flag': "ALTER TABLE messages ADD COLUMN read_flag BOOLEAN DEFAULT FALSE",
                    'created_at': "ALTER TABLE messages ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                }
                for col, alter in expected.items():
                    if col not in cols:
                        try:
                            conn.execute(text(alter))
                        except Exception:
                            logger.exception(f"Failed to add column {col} to messages")
                try:
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                logger.exception("Failed to verify messages schema")

    def get_user_by_email(self, email):
        # Normalize and perform case-insensitive lookup to be tolerant of user input
        if email is None:
            return None
        email_str = str(email).strip()
        query = text('SELECT id, email, password_hash, salt, role, COALESCE(full_name,"") as full_name, COALESCE(phone,"") as phone, COALESCE(avatar,"") as avatar, created_at FROM users WHERE LOWER(email)=LOWER(:email)')
        with self.get_connection() as conn:
            result = conn.execute(query, {"email": email_str})
            row = result.fetchone()
            if not row:
                return None
            # Row is a SQLAlchemy Row object; use mapping to convert to dict
            try:
                return dict(row._mapping)
            except Exception:
                return dict(row)

    def update_user_profile(self, user_id, full_name, phone):
        try:
            sql = text('UPDATE users SET full_name=:full_name, phone=:phone WHERE id=:id')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {'full_name': full_name, 'phone': phone, 'id': int(user_id)})
            return True
        except Exception:
            logger.exception(f"Failed to update profile for user_id={user_id}")
            return False

    def update_user_avatar(self, user_id, avatar_path):
        try:
            sql = text('UPDATE users SET avatar=:avatar WHERE id=:id')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {'avatar': avatar_path, 'id': int(user_id)})
            return True
        except Exception:
            logger.exception(f"Failed to update avatar for user_id={user_id}")
            return False

    def update_user_role(self, user_id, new_role):
        try:
            sql = text('UPDATE users SET role = :role WHERE id = :id')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {'role': new_role, 'id': int(user_id)})
            return True
        except Exception:
            logger.exception(f"Failed to update role for user_id={user_id}")
            return False

    def update_user_password(self, user_id, password_hash, salt):
        try:
            sql = text('UPDATE users SET password_hash = :password_hash, salt = :salt WHERE id = :id')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {'password_hash': password_hash, 'salt': salt, 'id': int(user_id)})
            return True
        except Exception:
            logger.exception(f"Failed to update password for user_id={user_id}")
            return False

    def __init__(self):
        # Prefer Streamlit secrets over environment variables to avoid stale env values
        try:
            secrets_url = st.secrets.get("DATABASE_URL", "")
        except Exception:
            secrets_url = ""

        # Also read environment variable for comparison
        env_url = os.getenv("DATABASE_URL") or ""

        # Debug output removed to avoid leaking DATABASE_URL in UI

        self.db_url = secrets_url or env_url or ""

        if not self.db_url:
            st.error("Database URL not configured. Add DATABASE_URL to Streamlit secrets or set DATABASE_URL environment variable.")
            st.stop()

        lower_url = self.db_url.lower()
        if not lower_url.startswith("mysql"):
            st.error(f"Configured DATABASE_URL does not appear to be MySQL: {self.db_url}\nPlease use a MySQL URL like: mysql+pymysql://root:12345678aA.@host:3307/eims")
            st.stop()
        if Database._engine is None:
            Database._engine = create_engine(
                self.db_url,
                pool_size=2,
                max_overflow=3,
                pool_pre_ping=True,
                pool_recycle=60,
                pool_timeout=8,
                echo=False,
                connect_args={
                    "connect_timeout": 5,
                    "read_timeout": 8,
                    "write_timeout": 8,
                }
            )
        # Ensure essential tables exist and schemas are up-to-date on construction
        try:
            # call init functions; they are idempotent
            self.init_users_table()
            self.init_leave_table()
            self.init_shipments_table()
            self.init_cargo_items_table()
            self.init_tracking_updates_table()
            self.init_documents_table()
            self.init_cargo_requests_table()
            self.init_messages_table()
            self.init_support_tickets_table()
            self.init_it_security_events_table()
            self.init_it_performance_monitoring_table()
            self.init_it_servers_status_table()
            self.init_it_activity_log_table()
            self.init_logistics_tables()
            self.init_finance_tables()
            self.init_cs_tables()
            self.init_admin_tables()
            self.init_sales_tables()
        except Exception:
            # log but don't prevent app startup
            logger.exception("Error ensuring DB schema on init")
        # Log that Database shim was initialized (helps confirm reloads)
        try:
            logger.info("Database shim initialized from database_mysql.py")
        except Exception:
            pass

    def get_connection(self):
        return Database._engine.connect()

    def execute_query(self, query, params=None):
        q = text(query) if isinstance(query, str) else query
        with self.get_connection() as conn:
            result = conn.execute(q, params or {})
            return result.fetchall()

    def execute_update(self, query, params=None):
        q = text(query) if isinstance(query, str) else query
        with self.get_connection() as conn:
            conn.execute(q, params or {})
            try:
                conn.commit()
            except Exception:
                # Some SQLAlchemy connections manage transactions differently; ignore if not available
                pass

    def fetch_dataframe(self, query, params=None):
        q = text(query) if isinstance(query, str) else query
        with self.get_connection() as conn:
            df = pd.read_sql(q, conn, params=params)
            return df

    # -- Convenience methods expected by App.py --
    def get_all_users(self):
        try:
            df = self.fetch_dataframe("SELECT id, email, role, created_at FROM users ORDER BY id DESC")
            return df
        except Exception:
            # If table missing or other error, return empty DataFrame
            return pd.DataFrame(columns=["id", "email", "role", "created_at"])

    def get_all_records(self):
        try:
            df = self.fetch_dataframe("SELECT * FROM company_records ORDER BY id DESC")
            return df
        except Exception:
            return pd.DataFrame()

    def create_user(self, email, password_hash, salt, role='employee'):
        try:
            # store email normalized (trimmed + lowercase) to avoid lookup issues
            email_norm = str(email).strip().lower() if email is not None else None
            sql = text('INSERT INTO users (email, password_hash, salt, role) VALUES (:email, :password_hash, :salt, :role)')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"email": email_norm, "password_hash": password_hash, "salt": salt, "role": role})
            return True
        except Exception:
            return False

    def add_record(self, employee_name, department, position, salary, hire_date, email, phone, status, password=None):
        try:
            sql = text('''
                INSERT INTO company_records (employee_name, department, position, salary, hire_date, email, phone, status)
                VALUES (:employee_name, :department, :position, :salary, :hire_date, :email, :phone, :status)
            ''')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"employee_name": employee_name, "department": department, "position": position, "salary": salary, "hire_date": hire_date, "email": email, "phone": phone, "status": status})
            return True
        except Exception:
            return False

    def update_record(self, record_id, employee_name, department, position, salary, hire_date, email, phone, status, password=None):
        try:
            sql = text('''
                UPDATE company_records
                SET employee_name = :employee_name,
                    department = :department,
                    position = :position,
                    salary = :salary,
                    hire_date = :hire_date,
                    email = :email,
                    phone = :phone,
                    status = :status
                WHERE id = :id
            ''')
            # `password` parameter is accepted for compatibility but handled by
            # the authentication/users layer; the records table does not store it.
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {
                        'employee_name': employee_name,
                        'department': department,
                        'position': position,
                        'salary': salary,
                        'hire_date': hire_date,
                        'email': email,
                        'phone': phone,
                        'status': status,
                        'id': int(record_id)
                    })
            return True
        except Exception:
            logger.exception("Failed to update record")
            return False

    def delete_record(self, record_id):
        try:
            sql = text('DELETE FROM company_records WHERE id = :id')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {'id': int(record_id)})
            return True
        except Exception:
            logger.exception("Failed to delete record")
            return False

    def search_records(self, search_term):
        q = f"SELECT * FROM company_records WHERE employee_name LIKE :p OR department LIKE :p OR position LIKE :p OR email LIKE :p ORDER BY id DESC"
        try:
            return self.fetch_dataframe(text(q), {"p": f"%{search_term}%"})
        except Exception:
            return pd.DataFrame()

    def get_all_shipments(self):
        try:
            # join with users to include client_email and alias columns to match App.py expectations
            sql = text('''
                SELECT
                    s.id,
                    s.shipment_number,
                    s.client_id,
                    s.shipment_type AS `type`,
                    s.origin AS origin_country,
                    s.destination AS destination_country,
                    s.departure_date,
                    s.expected_arrival,
                    s.total_weight,
                    s.total_value,
                    s.currency,
                    s.notes,
                    COALESCE(u.email, '') AS client_email,
                    s.created_at,
                    s.actual_arrival AS actual_arrival,
                    COALESCE(s.status, 'Pending') AS status,
                    COALESCE(s.customs_cleared, 0) AS customs_cleared
                FROM shipments s
                LEFT JOIN users u ON s.client_id = u.id
                ORDER BY s.id DESC
            ''')
            return self.fetch_dataframe(sql)
        except Exception:
            return pd.DataFrame()

    def create_shipment(self, shipment_number, client_id, shipment_type, origin_country, destination_country, departure_date, expected_arrival, total_weight=None, total_value=None, currency=None, notes=None):
        try:
            # normalize shipment number and check for existing shipment_number
            if shipment_number is None:
                return None
            shipment_number = str(shipment_number).strip()
            shipment_type_val = shipment_type
            check = text('SELECT id FROM shipments WHERE shipment_number = :sn')
            with self.get_connection() as conn:
                res = conn.execute(check, {"sn": shipment_number})
                row = res.fetchone()
                if row:
                    try:
                        return int(row[0])
                    except Exception:
                        try:
                            return int(row._mapping.get('id'))
                        except Exception:
                            return None

            # Build INSERT dynamically to account for legacy `type` column
            with self.get_connection() as conn:
                try:
                    # detect if legacy `type` column exists (some old schemas have `type` as NOT NULL)
                    res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'shipments'"))
                    cols = {r[0].lower() for r in res.fetchall()}

                    # Build insert columns dynamically depending on which schema exists
                    # Prefer `shipment_type` column, fall back to legacy `type` column if present.
                    type_col = None
                    if 'shipment_type' in cols:
                        type_col = 'shipment_type'
                    elif 'type' in cols:
                        type_col = 'type'

                    insert_cols = ['shipment_number', 'client_id']
                    if type_col:
                        insert_cols.append(type_col)
                    insert_cols += ['origin', 'destination', 'departure_date', 'expected_arrival', 'total_weight', 'total_value', 'currency', 'notes']

                    params = {
                        "shipment_number": shipment_number,
                        "client_id": client_id,
                        "origin": origin_country,
                        "destination": destination_country,
                        "departure_date": departure_date,
                        "expected_arrival": expected_arrival,
                        "total_weight": total_weight,
                        "total_value": total_value,
                        "currency": currency,
                        "notes": notes
                    }

                    if type_col:
                        params[type_col] = shipment_type_val
                    # Debug log to help identify which column name is being used at runtime
                    try:
                        logger.info(f"create_shipment chosen type column: {type_col}")
                    except Exception:
                        pass

                    col_list = ', '.join(insert_cols)
                    placeholder_list = ', '.join([f":{c}" for c in insert_cols])
                    sql = text(f'INSERT INTO shipments ({col_list}) VALUES ({placeholder_list})')

                    try:
                        conn.execute(sql, params)
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    except Exception as e:
                        logger.exception("Error inserting shipment")
                        return None
                    # after commit, fetch inserted id by selecting the row
                    res = conn.execute(text("SELECT id FROM shipments WHERE shipment_number = :sn ORDER BY id DESC LIMIT 1"), {"sn": shipment_number})
                    row = res.fetchone()
                    if not row:
                        return None
                    try:
                        return int(row[0])
                    except Exception:
                        try:
                            return int(row._mapping.get('id'))
                        except Exception:
                            return None
                except Exception as e:
                    logger.exception("Error inserting shipment")
                    return None
        except Exception as e:
            logger.exception("Unexpected error in create_shipment")
            return None

    def get_shipments_by_client(self, client_id):
        try:
            sql = text('''
                SELECT
                    s.id,
                    s.shipment_number,
                    s.client_id,
                    s.shipment_type AS `type`,
                    s.origin AS origin_country,
                    s.destination AS destination_country,
                    s.departure_date,
                    s.expected_arrival,
                    s.total_weight,
                    s.total_value,
                    s.currency,
                    s.notes,
                    COALESCE(u.email, '') AS client_email,
                    s.created_at,
                    s.actual_arrival AS actual_arrival,
                    COALESCE(s.status, 'Pending') AS status,
                    COALESCE(s.customs_cleared, 0) AS customs_cleared
                FROM shipments s
                LEFT JOIN users u ON s.client_id = u.id
                WHERE s.client_id = :cid
                ORDER BY s.id DESC
            ''')
            return self.fetch_dataframe(sql, {"cid": client_id})
        except Exception:
            return pd.DataFrame()

    def update_shipment_status(self, shipment_id, new_status, actual_arrival=None):
        try:
            # update status column if present; fallback to appending to notes if not
            with self.get_connection() as conn:
                # detect if status column exists
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'shipments'"))
                cols = {r[0].lower() for r in res.fetchall()}
                if 'status' in cols:
                    if actual_arrival:
                        sql = text('UPDATE shipments SET status = :status, actual_arrival = :actual WHERE id = :sid')
                        params = {"status": new_status, "actual": actual_arrival, "sid": shipment_id}
                    else:
                        sql = text('UPDATE shipments SET status = :status WHERE id = :sid')
                        params = {"status": new_status, "sid": shipment_id}
                    try:
                        conn.execute(sql, params)
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    except Exception:
                        logger.exception("Failed to execute status update")
                        return False
                else:
                    note = f"\nStatus updated to {new_status}"
                    if actual_arrival:
                        note += f"; actual_arrival={actual_arrival}"
                    sql = text("UPDATE shipments SET notes = CONCAT(IFNULL(notes,''), :note) WHERE id = :sid")
                    try:
                        conn.execute(sql, {"note": note, "sid": shipment_id})
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    except Exception:
                        logger.exception("Failed to append status note")
                        return False
            return True
        except Exception:
            logger.exception("Error updating shipment status")
            return False

    def update_customs_status(self, shipment_id, cleared_flag):
        try:
            with self.get_connection() as conn:
                # set customs_cleared if column exists, else append to notes
                res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'shipments'"))
                cols = {r[0].lower() for r in res.fetchall()}
                if 'customs_cleared' in cols:
                    sql = text('UPDATE shipments SET customs_cleared = :flag WHERE id = :sid')
                    try:
                        conn.execute(sql, {"flag": int(bool(cleared_flag)), "sid": shipment_id})
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    except Exception:
                        logger.exception("Failed to update customs_cleared")
                        return False
                else:
                    note = f"\nCustoms cleared: {int(bool(cleared_flag))}"
                    sql = text('UPDATE shipments SET notes = CONCAT(IFNULL(notes,''), :note) WHERE id = :sid')
                    try:
                        conn.execute(sql, {"note": note, "sid": shipment_id})
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    except Exception:
                        logger.exception("Failed to append customs note")
                        return False
            return True
        except Exception:
            logger.exception("Error updating customs status")
            return False

    def get_cargo_items_by_shipment(self, shipment_id):
        try:
            return self.fetch_dataframe(text('SELECT * FROM cargo_items WHERE shipment_id = :sid ORDER BY id DESC'), {"sid": shipment_id})
        except Exception:
            return pd.DataFrame()

    def get_shipment_statistics(self):
        """Return a dict with keys used by the analytics page.

        Keys: total_shipments, total_imports, total_exports, in_transit, total_value
        """
        try:
            sql = text('''
                SELECT
                    COUNT(*) AS total_shipments,
                    SUM(CASE WHEN LOWER(COALESCE(shipment_type,'')) LIKE '%import%' THEN 1 ELSE 0 END) AS total_imports,
                    SUM(CASE WHEN LOWER(COALESCE(shipment_type,'')) LIKE '%export%' THEN 1 ELSE 0 END) AS total_exports,
                    SUM(CASE WHEN expected_arrival IS NULL OR expected_arrival >= CURDATE() THEN 1 ELSE 0 END) AS in_transit,
                    COALESCE(SUM(total_value), 0) AS total_value
                FROM shipments
            ''')
            with self.get_connection() as conn:
                res = conn.execute(sql)
                row = res.fetchone()
                if not row:
                    return {
                        'total_shipments': 0,
                        'total_imports': 0,
                        'total_exports': 0,
                        'in_transit': 0,
                        'total_value': 0.0
                    }
                try:
                    mapping = row._mapping
                except Exception:
                    # fallback to positional
                    mapping = None
                if mapping is not None:
                    return {
                        'total_shipments': int(mapping.get('total_shipments') or 0),
                        'total_imports': int(mapping.get('total_imports') or 0),
                        'total_exports': int(mapping.get('total_exports') or 0),
                        'in_transit': int(mapping.get('in_transit') or 0),
                        'total_value': float(mapping.get('total_value') or 0.0)
                    }
                else:
                    return {
                        'total_shipments': int(row[0] or 0),
                        'total_imports': int(row[1] or 0),
                        'total_exports': int(row[2] or 0),
                        'in_transit': int(row[3] or 0),
                        'total_value': float(row[4] or 0.0)
                    }
        except Exception:
            logger.exception("Failed to compute shipment statistics")
            return {
                'total_shipments': 0,
                'total_imports': 0,
                'total_exports': 0,
                'in_transit': 0,
                'total_value': 0.0
            }

    # -- Cargo requests API expected by App.py --
    def create_cargo_request(self, cargo_item_id, user_id, request_type, reason):
        try:
            # Detect whether the cargo_requests table has a client_id column (legacy/newer schemas vary)
            try:
                with self.get_connection() as _det_conn:
                    res = _det_conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cargo_requests'"))
                    cols = {r[0].lower() for r in res.fetchall()}
            except Exception:
                cols = set()

            if 'client_id' in cols:
                sql = text('''
                    INSERT INTO cargo_requests (cargo_item_id, user_id, client_id, request_type, reason)
                    VALUES (:cargo_item_id, :user_id, :client_id, :request_type, :reason)
                ''')
                params = {"cargo_item_id": cargo_item_id, "user_id": user_id, "client_id": user_id, "request_type": request_type, "reason": reason}
            else:
                sql = text('''
                    INSERT INTO cargo_requests (cargo_item_id, user_id, request_type, reason)
                    VALUES (:cargo_item_id, :user_id, :request_type, :reason)
                ''')
                params = {"cargo_item_id": cargo_item_id, "user_id": user_id, "request_type": request_type, "reason": reason}

            # execute and commit on a fresh connection; avoid nested begin() calls
            conn = self.get_connection()
            try:
                conn.execute(sql, params)
                try:
                    conn.commit()
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            return True
        except Exception:
            logger.exception("Failed to create cargo request")
            return False

    def get_cargo_requests_by_client(self, client_id):
        try:
            # choose appropriate response column based on actual schema
            # Determine available response-like columns and attempt queries
            try:
                with self.get_connection() as conn:
                    res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cargo_requests'"))
                    cols = {r[0].lower() for r in res.fetchall()}
            except Exception:
                cols = set()

            # Candidate expressions to try in order
            candidates = []
            if 'response' in cols:
                candidates.append('cr.response AS employee_response')
            if 'employee_response' in cols:
                candidates.append('cr.employee_response AS employee_response')
            candidates.append('NULL AS employee_response')

            last_exc = None
            for resp_expr in candidates:
                sql_text = f'''
                    SELECT
                        cr.id,
                        cr.cargo_item_id,
                        cr.user_id,
                        cr.request_type,
                        cr.reason,
                        cr.status,
                        {resp_expr},
                        cr.created_at,
                        ci.item_name,
                        s.shipment_number,
                        COALESCE(u.email, '') AS client_email
                    FROM cargo_requests cr
                    LEFT JOIN cargo_items ci ON ci.id = cr.cargo_item_id
                    LEFT JOIN shipments s ON s.id = ci.shipment_id
                    LEFT JOIN users u ON u.id = cr.user_id
                    WHERE COALESCE(cr.client_id, cr.user_id) = :uid
                    ORDER BY cr.id DESC
                '''
                sql = text(sql_text)
                try:
                    with self.get_connection() as conn:
                        res = conn.execute(sql, {"uid": client_id})
                        rows = res.fetchall()
                    if not rows:
                        return pd.DataFrame()
                    records = []
                    for r in rows:
                        try:
                            records.append(dict(r._mapping))
                        except Exception:
                            records.append(dict(r))
                    return pd.DataFrame.from_records(records)
                except Exception as e:
                    last_exc = e
                    # try next candidate
                    continue
            # If all candidates failed, log and return empty DataFrame
            logger.exception('Failed to fetch cargo requests for client')
            return pd.DataFrame()
        except Exception:
            logger.exception("Failed to fetch cargo requests for client")
            return pd.DataFrame()

    def get_all_cargo_requests(self):
        try:
            # Determine available response-like columns and attempt queries
            try:
                with self.get_connection() as conn:
                    res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cargo_requests'"))
                    cols = {r[0].lower() for r in res.fetchall()}
            except Exception:
                cols = set()

            candidates = []
            if 'response' in cols:
                candidates.append('cr.response AS employee_response')
            if 'employee_response' in cols:
                candidates.append('cr.employee_response AS employee_response')
            candidates.append('NULL AS employee_response')

            for resp_expr in candidates:
                sql_text = f'''
                    SELECT
                        cr.id,
                        cr.cargo_item_id,
                        cr.user_id,
                        cr.request_type,
                        cr.reason,
                        cr.status,
                        {resp_expr},
                        cr.created_at,
                        ci.item_name,
                        s.shipment_number,
                        COALESCE(u.email, '') AS client_email
                    FROM cargo_requests cr
                    LEFT JOIN cargo_items ci ON ci.id = cr.cargo_item_id
                    LEFT JOIN shipments s ON s.id = ci.shipment_id
                    LEFT JOIN users u ON u.id = cr.user_id
                    ORDER BY cr.id DESC
                '''
                sql = text(sql_text)
                try:
                    with self.get_connection() as conn:
                        res = conn.execute(sql)
                        rows = res.fetchall()
                    if not rows:
                        return pd.DataFrame()
                    records = []
                    for r in rows:
                        try:
                            records.append(dict(r._mapping))
                        except Exception:
                            records.append(dict(r))
                    return pd.DataFrame.from_records(records)
                except Exception:
                    continue
            logger.exception('Failed to fetch all cargo requests')
            return pd.DataFrame()
        except Exception:
            logger.exception("Failed to fetch all cargo requests")
            return pd.DataFrame()

    def update_cargo_request_status(self, request_id, new_status, employee_response=None):
        try:
            sql = text('UPDATE cargo_requests SET status = :status, response = :response WHERE id = :rid')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"status": new_status, "response": employee_response, "rid": request_id})
            return True
        except Exception:
            logger.exception("Failed to update cargo request status")
            return False

    def delete_cargo_item(self, cargo_item_id):
        try:
            sql = text('DELETE FROM cargo_items WHERE id = :cid')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"cid": cargo_item_id})
            return True
        except Exception:
            logger.exception("Failed to delete cargo item")
            return False

    def add_cargo_item(self, shipment_id, item_name, description, quantity, unit, weight, value, hs_code=''):
        try:
            sql = text('''
                INSERT INTO cargo_items (shipment_id, item_name, description, quantity, unit, weight, value, hs_code)
                VALUES (:shipment_id, :item_name, :description, :quantity, :unit, :weight, :value, :hs_code)
            ''')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {
                        "shipment_id": shipment_id,
                        "item_name": item_name,
                        "description": description,
                        "quantity": quantity,
                        "unit": unit,
                        "weight": weight,
                        "value": value,
                        "hs_code": hs_code
                    })
            return True
        except Exception:
            logger.exception("Failed to add cargo item")
            return False

    def update_cargo_item(self, item_id, item_name=None, quantity=None, weight=None, unit=None, value=None, description=None, hs_code=None):
        try:
            # build dynamic set clause based on provided kwargs
            fields = []
            params = {"id": item_id}
            if item_name is not None:
                fields.append("item_name = :item_name")
                params['item_name'] = item_name
            if description is not None:
                fields.append("description = :description")
                params['description'] = description
            if quantity is not None:
                fields.append("quantity = :quantity")
                params['quantity'] = int(quantity)
            if unit is not None:
                fields.append("unit = :unit")
                params['unit'] = unit
            if weight is not None:
                fields.append("weight = :weight")
                params['weight'] = float(weight)
            if value is not None:
                fields.append("value = :value")
                params['value'] = float(value)
            if hs_code is not None:
                fields.append("hs_code = :hs_code")
                params['hs_code'] = hs_code

            if not fields:
                return True

            sql = text(f"UPDATE cargo_items SET {', '.join(fields)} WHERE id = :id")
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, params)
            return True
        except Exception:
            logger.exception("Failed to update cargo item")
            return False

    # -- Messaging API expected by App.py --
    def get_user_messages(self, user_id):
        try:
            sql = text('''
                SELECT
                    m.id,
                    m.from_user AS from_user_id,
                    m.to_user AS to_user_id,
                    COALESCE(uf.email, '') AS from_email,
                    COALESCE(ut.email, '') AS to_email,
                    m.subject,
                    m.content,
                    m.shipment_id,
                    s.shipment_number,
                    IFNULL(m.read_flag, 0) AS is_read,
                    m.created_at
                FROM messages m
                LEFT JOIN users uf ON uf.id = m.from_user
                LEFT JOIN users ut ON ut.id = m.to_user
                LEFT JOIN shipments s ON s.id = m.shipment_id
                WHERE m.from_user = :uid OR m.to_user = :uid
                ORDER BY m.created_at DESC
            ''')
            return self.fetch_dataframe(sql, {"uid": user_id})
        except Exception:
            logger.exception("Failed to fetch user messages")
            return pd.DataFrame()

    def get_unread_count(self, user_id):
        try:
            sql = text('SELECT COUNT(*) AS cnt FROM messages WHERE to_user = :uid AND IFNULL(read_flag,0)=0')
            with self.get_connection() as conn:
                res = conn.execute(sql, {"uid": user_id})
                row = res.fetchone()
                if not row:
                    return 0
                try:
                    return int(row[0])
                except Exception:
                    try:
                        return int(row._mapping.get('cnt') or 0)
                    except Exception:
                        return 0
        except Exception:
            logger.exception("Failed to get unread count")
            return 0

    def mark_message_read(self, message_id):
        try:
            sql = text('UPDATE messages SET read_flag = 1 WHERE id = :mid')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"mid": message_id})
            return True
        except Exception:
            logger.exception("Failed to mark message read")
            return False

    def count_unread_messages(self, user_id):
        try:
            with self.get_connection() as conn:
                row = conn.execute(text(
                    "SELECT COUNT(*) FROM messages WHERE to_user=:uid AND read_flag=0"
                ), {"uid": user_id}).fetchone()
                return int(row[0]) if row else 0
        except Exception:
            logger.exception("count_unread_messages failed")
            return 0

    def send_message(self, from_user_id, to_user_id, subject, content, shipment_id=None):
        try:
            sql = text('''
                INSERT INTO messages (from_user, to_user, subject, content, shipment_id)
                VALUES (:from_user, :to_user, :subject, :content, :shipment_id)
            ''')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"from_user": from_user_id, "to_user": to_user_id, "subject": subject, "content": content, "shipment_id": shipment_id})
            return True
        except Exception:
            logger.exception("Failed to send message")
            return False

    # -- Tracking and Documents API expected by App.py --
    def add_tracking_update(self, shipment_id, location, status, notes='', update_date=None, updated_by=None):
        try:
            # detect if older schema uses 'update_date' (DATE NOT NULL) instead of 'created_at'
            with self.get_connection() as conn:
                cols_res = conn.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tracking_updates'"))
                cols = {r[0].lower() for r in cols_res.fetchall()}

            params = {"shipment_id": shipment_id, "location": location, "status": status, "notes": notes or None, "updated_by": updated_by}

            if 'update_date' in cols:
                # ensure we have a date value (use today if not provided)
                import datetime
                if update_date:
                    ud = update_date
                else:
                    ud = datetime.date.today().isoformat()
                sql = text('''
                    INSERT INTO tracking_updates (shipment_id, location, status, notes, update_date, updated_by)
                    VALUES (:shipment_id, :location, :status, :notes, :update_date, :updated_by)
                ''')
                params['update_date'] = ud
            else:
                # modern schema: use created_at timestamp (can be provided or default)
                if update_date:
                    sql = text('''
                        INSERT INTO tracking_updates (shipment_id, location, status, notes, created_at, updated_by)
                        VALUES (:shipment_id, :location, :status, :notes, :created_at, :updated_by)
                    ''')
                    params['created_at'] = update_date
                else:
                    sql = text('''
                        INSERT INTO tracking_updates (shipment_id, location, status, notes, updated_by)
                        VALUES (:shipment_id, :location, :status, :notes, :updated_by)
                    ''')

            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, params)
            return True
        except Exception:
            logger.exception("Failed to add tracking update")
            return False

    def get_tracking_updates(self, shipment_id):
        try:
            sql = text('''
                SELECT
                    tu.id,
                    tu.shipment_id,
                    DATE_FORMAT(tu.created_at, '%Y-%m-%d') AS update_date,
                    tu.location,
                    tu.status,
                    tu.notes,
                    COALESCE(u.email, '') AS updated_by_email
                FROM tracking_updates tu
                LEFT JOIN users u ON u.id = tu.updated_by
                WHERE tu.shipment_id = :sid
                ORDER BY tu.created_at DESC
            ''')
            return self.fetch_dataframe(sql, {"sid": shipment_id})
        except Exception:
            logger.exception("Failed to fetch tracking updates")
            return pd.DataFrame()

    def get_shipment_documents(self, shipment_id):
        try:
            sql = text('''
                SELECT
                    d.id,
                    d.shipment_id,
                    d.doc_type AS document_type,
                    d.file_path,
                    COALESCE(u.email, '') AS uploaded_by_email,
                    d.notes,
                    d.created_at
                FROM documents d
                LEFT JOIN users u ON u.id = d.uploaded_by
                WHERE d.shipment_id = :sid
                ORDER BY d.created_at DESC
            ''')
            return self.fetch_dataframe(sql, {"sid": shipment_id})
        except Exception:
            logger.exception("Failed to fetch shipment documents")
            return pd.DataFrame()

    def add_shipment_document(self, shipment_id, doc_type, file_path, uploaded_by=None, notes=''):
        try:
            sql = text('''
                INSERT INTO documents (shipment_id, doc_type, file_path, uploaded_by, notes)
                VALUES (:shipment_id, :doc_type, :file_path, :uploaded_by, :notes)
            ''')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"shipment_id": shipment_id, "doc_type": doc_type, "file_path": file_path, "uploaded_by": uploaded_by, "notes": notes})
            return True
        except Exception:
            logger.exception("Failed to add shipment document")
            return False

    # -- Leave requests API expected by App.py --
    def create_leave_request(self, user_id, start_date, end_date, reason, leave_type='Other', attachment='', priority='Medium'):
        try:
            sql = text('''
                INSERT INTO leave_requests (user_id, start_date, end_date, reason, leave_type, attachment, priority)
                VALUES (:user_id, :start_date, :end_date, :reason, :leave_type, :attachment, :priority)
            ''')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"user_id": user_id, "start_date": start_date, "end_date": end_date, "reason": reason, "leave_type": leave_type, "attachment": attachment, "priority": priority})
            return True
        except Exception:
            logger.exception("Failed to create leave request")
            return False

    def get_leave_requests_by_user(self, user_id):
        try:
            sql = text('''
                SELECT
                    lr.id,
                    lr.user_id,
                    lr.start_date,
                    lr.end_date,
                    lr.reason,
                    lr.leave_type,
                    lr.attachment,
                    lr.status,
                    lr.priority,
                    lr.manager_response AS admin_response,
                    lr.created_at
                FROM leave_requests lr
                WHERE lr.user_id = :uid
                ORDER BY lr.id DESC
            ''')
            return self.fetch_dataframe(sql, {"uid": user_id})
        except Exception:
            logger.exception("Failed to fetch leave requests for user")
            return pd.DataFrame()

    def get_all_leave_requests(self):
        try:
            sql = text('''
                SELECT
                    lr.id,
                    lr.user_id,
                    COALESCE(u.email, '') AS user_email,
                    lr.start_date,
                    lr.end_date,
                    lr.reason,
                    lr.leave_type,
                    lr.attachment,
                    lr.status,
                    COALESCE(lr.priority, 'Medium') AS priority,
                    lr.manager_response AS admin_response,
                    lr.created_at
                FROM leave_requests lr
                LEFT JOIN users u ON u.id = lr.user_id
                ORDER BY FIELD(COALESCE(lr.priority,'Medium'), 'Urgent','High','Medium','Low'), lr.id DESC
            ''')
            return self.fetch_dataframe(sql)
        except Exception:
            logger.exception("Failed to fetch all leave requests")
            return pd.DataFrame()

    def update_leave_request_status(self, request_id, new_status, manager_response=None):
        try:
            sql = text('UPDATE leave_requests SET status = :status, manager_response = :mgr_resp WHERE id = :rid')
            with self.get_connection() as conn:
                with conn.begin():
                    conn.execute(sql, {"status": new_status, "mgr_resp": manager_response, "rid": request_id})
            return True
        except Exception:
            logger.exception("Failed to update leave request status")
            return False

    # ─────────────────────────── LOGISTICS ──────────────────────────

    def init_logistics_tables(self):
        with self.get_connection() as conn:
            # Add missing columns to shipments
            for col, definition in [
                ("freight_mode",    "VARCHAR(20)  DEFAULT 'Sea'"),
                ("carrier_name",    "VARCHAR(120) DEFAULT NULL"),
                ("container_type",  "VARCHAR(30)  DEFAULT NULL"),
                ("incoterms",       "VARCHAR(20)  DEFAULT NULL"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE shipments ADD COLUMN {col} {definition}"))
                    conn.commit()
                except Exception:
                    pass  # column already exists

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS logistics_routes (
                    id               INT AUTO_INCREMENT PRIMARY KEY,
                    route_name       VARCHAR(120) NOT NULL,
                    origin_port      VARCHAR(100) NOT NULL,
                    origin_country   VARCHAR(80)  NOT NULL,
                    destination_port VARCHAR(100) NOT NULL,
                    destination_country VARCHAR(80) NOT NULL,
                    freight_mode     VARCHAR(20)  NOT NULL DEFAULT 'Sea',
                    carrier          VARCHAR(100),
                    transit_days     INT,
                    frequency        VARCHAR(60),
                    status           VARCHAR(20)  DEFAULT 'Active',
                    notes            TEXT,
                    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def get_logistics_summary(self):
        try:
            with self.get_connection() as conn:
                r = conn.execute(text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='In Transit'       THEN 1 ELSE 0 END) AS in_transit,
                        SUM(CASE WHEN status='Delivered'        THEN 1 ELSE 0 END) AS delivered,
                        SUM(CASE WHEN status IN ('Pending','Customs') THEN 1 ELSE 0 END) AS pending,
                        SUM(CASE WHEN status != 'Delivered' AND expected_arrival < CURDATE() THEN 1 ELSE 0 END) AS overdue,
                        SUM(CASE WHEN status='Delivered' AND MONTH(actual_arrival)=MONTH(CURDATE()) AND YEAR(actual_arrival)=YEAR(CURDATE()) THEN 1 ELSE 0 END) AS delivered_this_month
                    FROM shipments
                """)).fetchone()
            return dict(total=int(r[0] or 0), in_transit=int(r[1] or 0),
                        delivered=int(r[2] or 0), pending=int(r[3] or 0),
                        overdue=int(r[4] or 0), delivered_this_month=int(r[5] or 0))
        except Exception:
            logger.exception("get_logistics_summary failed")
            return dict(total=0, in_transit=0, delivered=0, pending=0, overdue=0, delivered_this_month=0)

    def get_shipments_logistics(self, status_filter=None, mode_filter=None, type_filter=None):
        try:
            conditions = []
            params = {}
            if status_filter and status_filter != "All":
                conditions.append("s.status=:st"); params["st"] = status_filter
            if mode_filter and mode_filter != "All":
                conditions.append("s.freight_mode=:fm"); params["fm"] = mode_filter
            if type_filter and type_filter != "All":
                conditions.append("s.shipment_type=:tp"); params["tp"] = type_filter
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = text(f"""
                SELECT s.id, s.shipment_number, s.shipment_type, s.freight_mode,
                       s.origin, s.destination, s.carrier_name, s.container_type, s.incoterms,
                       s.departure_date, s.expected_arrival, s.actual_arrival,
                       s.total_weight, s.total_value, s.currency, s.status,
                       s.customs_cleared, s.notes,
                       COALESCE(u.email,'Unknown') AS client_email
                FROM shipments s
                LEFT JOIN users u ON s.client_id = u.id
                {where}
                ORDER BY s.id DESC
            """)
            return self.fetch_dataframe(sql, params)
        except Exception:
            logger.exception("get_shipments_logistics failed")
            return pd.DataFrame()

    def create_logistics_shipment(self, shipment_number, client_id, shipment_type, freight_mode,
                                   origin, destination, carrier_name, container_type, incoterms,
                                   departure_date, expected_arrival, total_weight, total_value, notes):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO shipments
                        (shipment_number,client_id,shipment_type,type,freight_mode,origin,destination,
                         origin_country,destination_country,carrier_name,container_type,incoterms,
                         departure_date,expected_arrival,total_weight,total_value,currency,status,notes)
                    VALUES
                        (:sn,:ci,:st,:st,:fm,:orig,:dest,:orig,:dest,:car,:cont,:inc,
                         :dep,:eta,:tw,:tv,'USD','Pending',:notes)
                """), dict(sn=shipment_number,ci=client_id,st=shipment_type,fm=freight_mode,
                           orig=origin,dest=destination,car=carrier_name,cont=container_type,
                           inc=incoterms,dep=departure_date,eta=expected_arrival,
                           tw=total_weight,tv=total_value,notes=notes))
                conn.commit()
            return True
        except Exception:
            logger.exception("create_logistics_shipment failed")
            return False

    def update_shipment_status_logistics(self, shipment_id, status):
        try:
            with self.get_connection() as conn:
                extra = ", actual_arrival=CURDATE()" if status == "Delivered" else ""
                conn.execute(text(f"UPDATE shipments SET status=:s{extra} WHERE id=:id"),
                             {"s": status, "id": shipment_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_shipment_status_logistics failed")
            return False

    def assign_carrier(self, shipment_id, carrier_name, container_type, incoterms):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    UPDATE shipments SET carrier_name=:car, container_type=:cont, incoterms=:inc,
                    status=CASE WHEN status='Pending' THEN 'Confirmed' ELSE status END
                    WHERE id=:id
                """), dict(car=carrier_name, cont=container_type, inc=incoterms, id=shipment_id))
                conn.commit()
            return True
        except Exception:
            logger.exception("assign_carrier failed")
            return False

    def add_tracking_update_logistics(self, shipment_id, location, status, notes, created_by):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO tracking_updates (shipment_id,location,status,notes,update_date,created_by,user_id)
                    VALUES (:sid,:loc,:st,:notes,CURDATE(),:cb,:cb)
                """), dict(sid=shipment_id,loc=location,st=status,notes=notes,cb=created_by))
                conn.execute(text("UPDATE shipments SET status=:s WHERE id=:id"),
                             {"s": status, "id": shipment_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("add_tracking_update_logistics failed")
            return False

    def get_tracking_history(self, shipment_id):
        try:
            return self.fetch_dataframe(
                text("SELECT location,status,notes,update_date FROM tracking_updates WHERE shipment_id=:sid ORDER BY created_at ASC"),
                {"sid": shipment_id}
            )
        except Exception:
            logger.exception("get_tracking_history failed")
            return pd.DataFrame()

    def get_cargo_items_for_shipment(self, shipment_id):
        try:
            return self.fetch_dataframe(
                text("SELECT item_name,description,quantity,unit,weight,value,hs_code FROM cargo_items WHERE shipment_id=:sid"),
                {"sid": shipment_id}
            )
        except Exception:
            logger.exception("get_cargo_items_for_shipment failed")
            return pd.DataFrame()

    def get_all_routes(self, status_filter=None):
        try:
            where = "WHERE status=:s" if status_filter and status_filter != "All" else ""
            params = {"s": status_filter} if where else {}
            return self.fetch_dataframe(f"SELECT * FROM logistics_routes {where} ORDER BY id DESC", params)
        except Exception:
            logger.exception("get_all_routes failed")
            return pd.DataFrame()

    def add_route(self, route_name, origin_port, origin_country, destination_port, destination_country,
                  freight_mode, carrier, transit_days, frequency, notes):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO logistics_routes
                        (route_name,origin_port,origin_country,destination_port,destination_country,
                         freight_mode,carrier,transit_days,frequency,notes)
                    VALUES (:rn,:op,:oc,:dp,:dc,:fm,:car,:td,:freq,:notes)
                """), dict(rn=route_name,op=origin_port,oc=origin_country,dp=destination_port,
                           dc=destination_country,fm=freight_mode,car=carrier,
                           td=transit_days,freq=frequency,notes=notes))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_route failed")
            return False

    def get_monthly_shipment_volume(self):
        try:
            return self.fetch_dataframe("""
                SELECT DATE_FORMAT(departure_date,'%Y-%m') AS month,
                       COUNT(*) AS count,
                       shipment_type AS type
                FROM shipments
                WHERE departure_date IS NOT NULL
                GROUP BY month, shipment_type
                ORDER BY month
            """)
        except Exception:
            logger.exception("get_monthly_shipment_volume failed")
            return pd.DataFrame()

    # ─────────────────────────── FINANCE ────────────────────────────

    def init_finance_tables(self):
        with self.get_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS finance_invoices (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    invoice_number  VARCHAR(30) UNIQUE NOT NULL,
                    client_name     VARCHAR(120) NOT NULL,
                    client_email    VARCHAR(120),
                    shipment_ref    VARCHAR(60),
                    amount          DECIMAL(14,2) NOT NULL DEFAULT 0,
                    tax_rate        DECIMAL(5,2)  NOT NULL DEFAULT 0,
                    tax_amount      DECIMAL(14,2) NOT NULL DEFAULT 0,
                    total           DECIMAL(14,2) NOT NULL DEFAULT 0,
                    status          VARCHAR(20)   NOT NULL DEFAULT 'Draft',
                    issue_date      DATE          NOT NULL,
                    due_date        DATE          NOT NULL,
                    description     TEXT,
                    created_by      INT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            try:
                conn.execute(text("ALTER TABLE finance_invoices ADD COLUMN client_email VARCHAR(120)"))
                conn.commit()
            except Exception:
                pass
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS finance_payments (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    invoice_id      INT NOT NULL,
                    amount          DECIMAL(14,2) NOT NULL,
                    payment_date    DATE NOT NULL,
                    method          VARCHAR(40) NOT NULL DEFAULT 'Bank Transfer',
                    reference_no    VARCHAR(80),
                    notes           TEXT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (invoice_id) REFERENCES finance_invoices(id) ON DELETE CASCADE
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS finance_expenses (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    category        VARCHAR(60) NOT NULL,
                    description     TEXT NOT NULL,
                    amount          DECIMAL(14,2) NOT NULL,
                    expense_date    DATE NOT NULL,
                    vendor          VARCHAR(120),
                    receipt_ref     VARCHAR(80),
                    status          VARCHAR(20) NOT NULL DEFAULT 'Pending',
                    created_by      INT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def get_finance_summary(self):
        try:
            with self.get_connection() as conn:
                r = conn.execute(text("""
                    SELECT
                        COALESCE(SUM(CASE WHEN status='Paid'    THEN total ELSE 0 END),0) AS total_revenue,
                        COALESCE(SUM(CASE WHEN status='Unpaid'  THEN total ELSE 0 END),0) AS outstanding,
                        COALESCE(SUM(CASE WHEN status='Overdue' THEN total ELSE 0 END),0) AS overdue,
                        COUNT(*) AS total_invoices,
                        COALESCE(SUM(CASE WHEN status='Paid' THEN 1 ELSE 0 END),0) AS paid_count
                    FROM finance_invoices
                """)).fetchone()
                exp = conn.execute(text(
                    "SELECT COALESCE(SUM(amount),0) FROM finance_expenses WHERE status='Approved'"
                )).fetchone()
            return {
                "total_revenue":  float(r[0]),
                "outstanding":    float(r[1]),
                "overdue":        float(r[2]),
                "total_invoices": int(r[3]),
                "paid_count":     int(r[4]),
                "total_expenses": float(exp[0]),
                "net_profit":     float(r[0]) - float(exp[0]),
            }
        except Exception:
            logger.exception("get_finance_summary failed")
            return {"total_revenue":0,"outstanding":0,"overdue":0,"total_invoices":0,"paid_count":0,"total_expenses":0,"net_profit":0}

    def get_invoices(self, status_filter=None):
        try:
            where = "WHERE status=:s" if status_filter and status_filter != "All" else ""
            params = {"s": status_filter} if where else {}
            return self.fetch_dataframe(f"SELECT * FROM finance_invoices {where} ORDER BY created_at DESC", params)
        except Exception:
            logger.exception("get_invoices failed")
            return pd.DataFrame()

    def create_invoice(self, invoice_number, client_name, client_email, shipment_ref, amount, tax_rate, due_date, description, created_by):
        try:
            tax_amount = round(amount * tax_rate / 100, 2)
            total      = round(amount + tax_amount, 2)
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO finance_invoices
                        (invoice_number,client_name,client_email,shipment_ref,amount,tax_rate,tax_amount,total,status,issue_date,due_date,description,created_by)
                    VALUES (:inv,:cn,:ce,:sr,:am,:tr,:ta,:tot,'Draft',CURDATE(),:dd,:desc,:cb)
                """), dict(inv=invoice_number,cn=client_name,ce=client_email,sr=shipment_ref,am=amount,
                           tr=tax_rate,ta=tax_amount,tot=total,dd=due_date,desc=description,cb=created_by))
                conn.commit()
            return True
        except Exception:
            logger.exception("create_invoice failed")
            return False

    def update_invoice_status(self, invoice_id, status):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE finance_invoices SET status=:s WHERE id=:id"), {"s":status,"id":invoice_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_invoice_status failed")
            return False

    def delete_invoice(self, invoice_id):
        try:
            with self.get_connection() as conn:
                conn.execute(text("DELETE FROM finance_invoices WHERE id=:id"), {"id":invoice_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("delete_invoice failed")
            return False

    def add_payment(self, invoice_id, amount, payment_date, method, reference_no, notes):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO finance_payments (invoice_id,amount,payment_date,method,reference_no,notes)
                    VALUES (:iid,:am,:pd,:meth,:ref,:notes)
                """), dict(iid=invoice_id,am=amount,pd=payment_date,meth=method,ref=reference_no,notes=notes))
                conn.execute(text("UPDATE finance_invoices SET status='Paid' WHERE id=:id"), {"id":invoice_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("add_payment failed")
            return False

    def get_payments(self):
        try:
            return self.fetch_dataframe("""
                SELECT p.*, i.invoice_number, i.client_name, i.total AS invoice_total
                FROM finance_payments p
                LEFT JOIN finance_invoices i ON i.id=p.invoice_id
                ORDER BY p.payment_date DESC
            """)
        except Exception:
            logger.exception("get_payments failed")
            return pd.DataFrame()

    def get_expenses(self, status_filter=None):
        try:
            where = "WHERE status=:s" if status_filter and status_filter != "All" else ""
            params = {"s": status_filter} if where else {}
            return self.fetch_dataframe(f"SELECT * FROM finance_expenses {where} ORDER BY expense_date DESC", params)
        except Exception:
            logger.exception("get_expenses failed")
            return pd.DataFrame()

    def add_expense(self, category, description, amount, expense_date, vendor, receipt_ref, created_by):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO finance_expenses (category,description,amount,expense_date,vendor,receipt_ref,status,created_by)
                    VALUES (:cat,:desc,:am,:ed,:ven,:rec,'Pending',:cb)
                """), dict(cat=category,desc=description,am=amount,ed=expense_date,ven=vendor,rec=receipt_ref,cb=created_by))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_expense failed")
            return False

    def update_expense_status(self, expense_id, status):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE finance_expenses SET status=:s WHERE id=:id"), {"s":status,"id":expense_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_expense_status failed")
            return False

    def get_monthly_financials(self):
        try:
            rev = self.fetch_dataframe("""
                SELECT DATE_FORMAT(issue_date,'%Y-%m') AS month,
                       SUM(total) AS revenue
                FROM finance_invoices WHERE status='Paid'
                GROUP BY month ORDER BY month
            """)
            exp = self.fetch_dataframe("""
                SELECT DATE_FORMAT(expense_date,'%Y-%m') AS month,
                       SUM(amount) AS expenses
                FROM finance_expenses WHERE status='Approved'
                GROUP BY month ORDER BY month
            """)
            return rev, exp
        except Exception:
            logger.exception("get_monthly_financials failed")
            return pd.DataFrame(), pd.DataFrame()

    # ──────────────────────── CUSTOMER SERVICE ───────────────────────

    def init_cs_tables(self):
        with self.get_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cs_tickets (
                    id             INT AUTO_INCREMENT PRIMARY KEY,
                    ticket_number  VARCHAR(30) UNIQUE NOT NULL,
                    client_name    VARCHAR(120) NOT NULL,
                    client_email   VARCHAR(120),
                    client_id      INT,
                    category       VARCHAR(60)  NOT NULL DEFAULT 'General Inquiry',
                    subject        VARCHAR(200) NOT NULL,
                    description    TEXT         NOT NULL,
                    priority       VARCHAR(20)  NOT NULL DEFAULT 'Medium',
                    status         VARCHAR(20)  NOT NULL DEFAULT 'Open',
                    assigned_to    INT,
                    resolution     TEXT,
                    shipment_ref   VARCHAR(60),
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at    DATETIME
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cs_ticket_replies (
                    id                INT AUTO_INCREMENT PRIMARY KEY,
                    ticket_id         INT NOT NULL,
                    sender_role       VARCHAR(20) NOT NULL DEFAULT 'client',
                    sender_email      VARCHAR(120),
                    message           TEXT NOT NULL,
                    is_read_by_client TINYINT NOT NULL DEFAULT 0,
                    is_read_by_cs     TINYINT NOT NULL DEFAULT 0,
                    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            # Add read-tracking columns to existing table if missing
            for col, defn in [
                ("is_read_by_client", "TINYINT NOT NULL DEFAULT 0"),
                ("is_read_by_cs",     "TINYINT NOT NULL DEFAULT 0"),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE cs_ticket_replies ADD COLUMN {col} {defn}"
                    ))
                except Exception:
                    pass
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cs_feedback (
                    id             INT AUTO_INCREMENT PRIMARY KEY,
                    client_name    VARCHAR(120) NOT NULL,
                    client_email   VARCHAR(120),
                    client_id      INT,
                    rating         TINYINT      NOT NULL DEFAULT 3,
                    category       VARCHAR(60)  NOT NULL DEFAULT 'Overall',
                    comment        TEXT,
                    shipment_ref   VARCHAR(60),
                    is_read        TINYINT      NOT NULL DEFAULT 0,
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def get_cs_summary(self):
        try:
            with self.get_connection() as conn:
                t = conn.execute(text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status='Open'        THEN 1 ELSE 0 END) AS open_count,
                        SUM(CASE WHEN status='In Progress' THEN 1 ELSE 0 END) AS in_progress,
                        SUM(CASE WHEN status='Resolved' AND DATE(resolved_at)=CURDATE() THEN 1 ELSE 0 END) AS resolved_today,
                        SUM(CASE WHEN priority='Urgent'    THEN 1 ELSE 0 END) AS urgent
                    FROM cs_tickets
                """)).fetchone()
                f = conn.execute(text("""
                    SELECT ROUND(AVG(rating),1), SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END)
                    FROM cs_feedback
                """)).fetchone()
            return dict(total=int(t[0] or 0), open_count=int(t[1] or 0),
                        in_progress=int(t[2] or 0), resolved_today=int(t[3] or 0),
                        urgent=int(t[4] or 0),
                        avg_rating=float(f[0] or 0), unread_feedback=int(f[1] or 0))
        except Exception:
            logger.exception("get_cs_summary failed")
            return dict(total=0,open_count=0,in_progress=0,resolved_today=0,urgent=0,avg_rating=0,unread_feedback=0)

    def get_cs_tickets(self, status_filter=None, priority_filter=None, category_filter=None):
        try:
            conds, params = [], {}
            if status_filter and status_filter != "All":
                conds.append("status=:st"); params["st"] = status_filter
            if priority_filter and priority_filter != "All":
                conds.append("priority=:pr"); params["pr"] = priority_filter
            if category_filter and category_filter != "All":
                conds.append("category=:cat"); params["cat"] = category_filter
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            return self.fetch_dataframe(f"SELECT * FROM cs_tickets {where} ORDER BY created_at DESC", params)
        except Exception:
            logger.exception("get_cs_tickets failed")
            return pd.DataFrame()

    def create_cs_ticket(self, ticket_number, client_name, client_email, client_id,
                         category, subject, description, priority, shipment_ref):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO cs_tickets
                        (ticket_number,client_name,client_email,client_id,category,subject,
                         description,priority,status,shipment_ref)
                    VALUES (:tn,:cn,:ce,:ci,:cat,:sub,:desc,:pr,'Open',:sr)
                """), dict(tn=ticket_number,cn=client_name,ce=client_email,ci=client_id,
                           cat=category,sub=subject,desc=description,pr=priority,sr=shipment_ref))
                conn.commit()
            return True
        except Exception:
            logger.exception("create_cs_ticket failed")
            return False

    def update_cs_ticket(self, ticket_id, status, resolution=None, assigned_to=None):
        try:
            with self.get_connection() as conn:
                resolved_clause = ", resolved_at=NOW()" if status in ("Resolved","Closed") else ""
                assign_clause   = ", assigned_to=:at" if assigned_to is not None else ""
                conn.execute(text(f"""
                    UPDATE cs_tickets
                    SET status=:st, resolution=COALESCE(:res, resolution){resolved_clause}{assign_clause}
                    WHERE id=:id
                """), dict(st=status, res=resolution, at=assigned_to, id=ticket_id))
                conn.commit()
            return True
        except Exception:
            logger.exception("update_cs_ticket failed")
            return False

    def delete_cs_ticket(self, ticket_id):
        try:
            with self.get_connection() as conn:
                conn.execute(text("DELETE FROM cs_tickets WHERE id=:id"), {"id": ticket_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("delete_cs_ticket failed")
            return False

    def add_ticket_reply(self, ticket_id, sender_role, sender_email, message):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO cs_ticket_replies (ticket_id, sender_role, sender_email, message)
                    VALUES (:tid, :role, :email, :msg)
                """), dict(tid=ticket_id, role=sender_role, email=sender_email, msg=message))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_ticket_reply failed")
            return False

    def get_ticket_replies(self, ticket_id):
        try:
            return self.fetch_dataframe(
                "SELECT * FROM cs_ticket_replies WHERE ticket_id=:tid ORDER BY created_at ASC",
                {"tid": ticket_id}
            )
        except Exception:
            logger.exception("get_ticket_replies failed")
            return pd.DataFrame()

    def mark_ticket_replies_read(self, ticket_id, reader_role):
        col = "is_read_by_client" if reader_role == "client" else "is_read_by_cs"
        try:
            with self.get_connection() as conn:
                conn.execute(text(
                    f"UPDATE cs_ticket_replies SET {col}=1 WHERE ticket_id=:tid AND sender_role!=:role"
                ), {"tid": ticket_id, "role": reader_role})
                conn.commit()
        except Exception:
            logger.exception("mark_ticket_replies_read failed")

    def get_all_unread_counts(self, reader_role, client_id=None):
        col = "is_read_by_client" if reader_role == "client" else "is_read_by_cs"
        try:
            if reader_role == "client" and client_id:
                df = self.fetch_dataframe(f"""
                    SELECT r.ticket_id, COUNT(*) AS cnt
                    FROM cs_ticket_replies r
                    JOIN cs_tickets t ON r.ticket_id=t.id
                    WHERE t.client_id=:cid AND r.sender_role='cs' AND r.{col}=0
                    GROUP BY r.ticket_id
                """, {"cid": client_id})
            else:
                df = self.fetch_dataframe(f"""
                    SELECT ticket_id, COUNT(*) AS cnt
                    FROM cs_ticket_replies
                    WHERE sender_role='client' AND {col}=0
                    GROUP BY ticket_id
                """)
            if df is None or df.empty:
                return {}
            return {int(r["ticket_id"]): int(r["cnt"]) for _, r in df.iterrows()}
        except Exception:
            logger.exception("get_all_unread_counts failed")
            return {}

    def edit_cs_ticket(self, ticket_id, subject, description, category, priority):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    UPDATE cs_tickets
                    SET subject=:sub, description=:desc, category=:cat, priority=:pr
                    WHERE id=:id
                """), dict(sub=subject, desc=description, cat=category, pr=priority, id=ticket_id))
                conn.commit()
            return True
        except Exception:
            logger.exception("edit_cs_ticket failed")
            return False

    def get_cs_feedback(self, unread_only=False):
        try:
            where = "WHERE is_read=0" if unread_only else ""
            return self.fetch_dataframe(f"SELECT * FROM cs_feedback {where} ORDER BY created_at DESC")
        except Exception:
            logger.exception("get_cs_feedback failed")
            return pd.DataFrame()

    def add_cs_feedback(self, client_name, client_email, client_id, rating, category, comment, shipment_ref):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO cs_feedback (client_name,client_email,client_id,rating,category,comment,shipment_ref)
                    VALUES (:cn,:ce,:ci,:r,:cat,:comm,:sr)
                """), dict(cn=client_name,ce=client_email,ci=client_id,r=rating,
                           cat=category,comm=comment,sr=shipment_ref))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_cs_feedback failed")
            return False

    def edit_cs_feedback(self, feedback_id, rating, category, comment):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    UPDATE cs_feedback
                    SET rating=:r, category=:cat, comment=:com
                    WHERE id=:id
                """), dict(r=rating, cat=category, com=comment, id=feedback_id))
                conn.commit()
            return True
        except Exception:
            logger.exception("edit_cs_feedback failed")
            return False

    def delete_cs_feedback(self, feedback_id):
        try:
            with self.get_connection() as conn:
                conn.execute(text("DELETE FROM cs_feedback WHERE id=:id"), {"id": feedback_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("delete_cs_feedback failed")
            return False

    def mark_feedback_read(self, feedback_id):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE cs_feedback SET is_read=1 WHERE id=:id"), {"id": feedback_id})
                conn.commit()
        except Exception:
            logger.exception("mark_feedback_read failed")

    # ──────────────────────── ADMINISTRATION ─────────────────────────

    def init_admin_tables(self):
        with self.get_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_documents (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    title        VARCHAR(200) NOT NULL,
                    category     VARCHAR(60)  NOT NULL DEFAULT 'Other',
                    description  TEXT,
                    file_name    VARCHAR(200),
                    status       VARCHAR(20)  NOT NULL DEFAULT 'Active',
                    expiry_date  DATE,
                    uploaded_by  INT,
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_meetings (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    title         VARCHAR(200) NOT NULL,
                    meeting_type  VARCHAR(60)  NOT NULL DEFAULT 'Internal',
                    attendees     TEXT,
                    location      VARCHAR(150),
                    meeting_date  DATE         NOT NULL,
                    meeting_time  TIME,
                    duration_min  INT          DEFAULT 60,
                    status        VARCHAR(20)  NOT NULL DEFAULT 'Scheduled',
                    agenda        TEXT,
                    minutes       TEXT,
                    created_by    INT,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_contracts (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    contract_number VARCHAR(40)  UNIQUE NOT NULL,
                    title           VARCHAR(200) NOT NULL,
                    party_name      VARCHAR(150) NOT NULL,
                    party_type      VARCHAR(60)  NOT NULL DEFAULT 'Carrier',
                    contract_type   VARCHAR(60)  NOT NULL DEFAULT 'Service Agreement',
                    value           DECIMAL(14,2),
                    currency        VARCHAR(10)  DEFAULT 'USD',
                    start_date      DATE         NOT NULL,
                    end_date        DATE         NOT NULL,
                    status          VARCHAR(20)  NOT NULL DEFAULT 'Active',
                    description     TEXT,
                    created_by      INT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_training_programs (
                    id               INT AUTO_INCREMENT PRIMARY KEY,
                    title            VARCHAR(200) NOT NULL,
                    category         VARCHAR(60)  NOT NULL DEFAULT 'Other',
                    description      TEXT,
                    trainer          VARCHAR(150),
                    duration_hours   INT          NOT NULL DEFAULT 8,
                    max_participants INT          NOT NULL DEFAULT 20,
                    scheduled_date   DATE         NOT NULL,
                    status           VARCHAR(20)  NOT NULL DEFAULT 'Scheduled',
                    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_training_enrollments (
                    id             INT AUTO_INCREMENT PRIMARY KEY,
                    program_id     INT          NOT NULL,
                    employee_name  VARCHAR(150),
                    employee_email VARCHAR(150),
                    user_id        INT,
                    status         VARCHAR(20)  NOT NULL DEFAULT 'Enrolled',
                    score          DECIMAL(5,2),
                    completed_at   DATETIME,
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_prog_user (program_id, user_id)
                )
            """))
            conn.commit()

    def get_admin_summary(self):
        try:
            with self.get_connection() as conn:
                d = conn.execute(text("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END)
                    FROM admin_documents
                """)).fetchone()
                m = conn.execute(text("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN status='Scheduled' AND meeting_date >= CURDATE() THEN 1 ELSE 0 END)
                    FROM admin_meetings
                """)).fetchone()
                c = conn.execute(text("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END),
                           SUM(CASE WHEN status='Active' AND end_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(),INTERVAL 30 DAY) THEN 1 ELSE 0 END)
                    FROM admin_contracts
                """)).fetchone()
            return dict(
                total_docs=int(d[0] or 0), active_docs=int(d[1] or 0),
                total_meetings=int(m[0] or 0), upcoming_meetings=int(m[1] or 0),
                total_contracts=int(c[0] or 0), active_contracts=int(c[1] or 0),
                expiring_soon=int(c[2] or 0)
            )
        except Exception:
            logger.exception("get_admin_summary failed")
            return dict(total_docs=0,active_docs=0,total_meetings=0,upcoming_meetings=0,
                        total_contracts=0,active_contracts=0,expiring_soon=0)

    def get_admin_documents(self, category=None, status=None):
        try:
            conds, params = [], {}
            if category and category != "All":
                conds.append("category=:cat"); params["cat"] = category
            if status and status != "All":
                conds.append("status=:st"); params["st"] = status
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            return self.fetch_dataframe(f"SELECT * FROM admin_documents {where} ORDER BY created_at DESC", params)
        except Exception:
            logger.exception("get_admin_documents failed")
            return pd.DataFrame()

    def add_document(self, title, category, description, file_name, status, expiry_date, uploaded_by):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO admin_documents (title,category,description,file_name,status,expiry_date,uploaded_by)
                    VALUES (:t,:cat,:desc,:fn,:st,:exp,:ub)
                """), dict(t=title,cat=category,desc=description,fn=file_name,
                           st=status,exp=expiry_date or None,ub=uploaded_by))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_document failed")
            return False

    def update_document_status(self, doc_id, status):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE admin_documents SET status=:s WHERE id=:id"), {"s":status,"id":doc_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_document_status failed")
            return False

    def get_admin_meetings(self, upcoming_only=False):
        try:
            where = "WHERE meeting_date >= CURDATE()" if upcoming_only else ""
            return self.fetch_dataframe(f"SELECT * FROM admin_meetings {where} ORDER BY meeting_date ASC, meeting_time ASC")
        except Exception:
            logger.exception("get_admin_meetings failed")
            return pd.DataFrame()

    def add_meeting(self, title, meeting_type, attendees, location, meeting_date,
                    meeting_time, duration_min, agenda, created_by):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO admin_meetings
                        (title,meeting_type,attendees,location,meeting_date,meeting_time,duration_min,agenda,created_by)
                    VALUES (:t,:mt,:att,:loc,:md,:mtime,:dur,:ag,:cb)
                """), dict(t=title,mt=meeting_type,att=attendees,loc=location,md=meeting_date,
                           mtime=meeting_time,dur=duration_min,ag=agenda,cb=created_by))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_meeting failed")
            return False

    def update_meeting(self, meeting_id, status, minutes=None):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    UPDATE admin_meetings SET status=:s, minutes=COALESCE(:m, minutes) WHERE id=:id
                """), {"s":status,"m":minutes,"id":meeting_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_meeting failed")
            return False

    def get_admin_contracts(self, status=None, party_type=None):
        try:
            conds, params = [], {}
            if status and status != "All":
                conds.append("status=:st"); params["st"] = status
            if party_type and party_type != "All":
                conds.append("party_type=:pt"); params["pt"] = party_type
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            return self.fetch_dataframe(f"SELECT * FROM admin_contracts {where} ORDER BY end_date ASC", params)
        except Exception:
            logger.exception("get_admin_contracts failed")
            return pd.DataFrame()

    def add_contract(self, contract_number, title, party_name, party_type, contract_type,
                     value, currency, start_date, end_date, description, created_by):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO admin_contracts
                        (contract_number,title,party_name,party_type,contract_type,value,currency,
                         start_date,end_date,status,description,created_by)
                    VALUES (:cn,:t,:pn,:pt,:ct,:val,:cur,:sd,:ed,'Active',:desc,:cb)
                """), dict(cn=contract_number,t=title,pn=party_name,pt=party_type,ct=contract_type,
                           val=value,cur=currency,sd=start_date,ed=end_date,desc=description,cb=created_by))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_contract failed")
            return False

    def update_contract_status(self, contract_id, status):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE admin_contracts SET status=:s WHERE id=:id"), {"s":status,"id":contract_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_contract_status failed")
            return False

    # ── Sales ─────────────────────────────────────────────────────────
    def init_sales_tables(self):
        with self.get_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sales_leads (
                    id               INT AUTO_INCREMENT PRIMARY KEY,
                    lead_name        VARCHAR(150) NOT NULL,
                    company_name     VARCHAR(150),
                    email            VARCHAR(150),
                    phone            VARCHAR(40),
                    country          VARCHAR(80),
                    source           VARCHAR(60)  NOT NULL DEFAULT 'Other',
                    status           VARCHAR(40)  NOT NULL DEFAULT 'New',
                    freight_interest VARCHAR(60),
                    notes            TEXT,
                    assigned_to_id   INT,
                    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sales_deals (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    lead_id         INT,
                    title           VARCHAR(200) NOT NULL,
                    client_name     VARCHAR(150) NOT NULL,
                    value           DECIMAL(14,2),
                    currency        VARCHAR(10)  DEFAULT 'USD',
                    stage           VARCHAR(40)  NOT NULL DEFAULT 'Discovery',
                    probability     INT          DEFAULT 50,
                    close_date      DATE,
                    freight_type    VARCHAR(60),
                    origin          VARCHAR(80),
                    destination     VARCHAR(80),
                    notes           TEXT,
                    assigned_to_id  INT,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sales_offers (
                    id             INT AUTO_INCREMENT PRIMARY KEY,
                    offer_number   VARCHAR(40)  UNIQUE NOT NULL,
                    deal_id        INT,
                    client_name    VARCHAR(150) NOT NULL,
                    client_email   VARCHAR(150),
                    freight_type   VARCHAR(60),
                    origin         VARCHAR(80),
                    destination    VARCHAR(80),
                    commodity      VARCHAR(150),
                    weight_kg      DECIMAL(10,2),
                    volume_cbm     DECIMAL(10,2),
                    total_value    DECIMAL(14,2),
                    currency       VARCHAR(10)  DEFAULT 'USD',
                    validity_date  DATE,
                    status         VARCHAR(20)  NOT NULL DEFAULT 'Draft',
                    notes          TEXT,
                    created_by     INT,
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def get_sales_summary(self):
        try:
            with self.get_connection() as conn:
                l = conn.execute(text("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN status IN ('New','Contacted','Qualified') THEN 1 ELSE 0 END)
                    FROM sales_leads
                """)).fetchone()
                d = conn.execute(text("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN stage NOT IN ('Won','Lost') THEN value ELSE 0 END),
                           SUM(CASE WHEN stage='Won' THEN 1 ELSE 0 END),
                           COUNT(CASE WHEN stage IN ('Won','Lost') THEN 1 END)
                    FROM sales_deals
                """)).fetchone()
                o = conn.execute(text("""
                    SELECT COUNT(*),
                           SUM(CASE WHEN status='Sent' THEN 1 ELSE 0 END)
                    FROM sales_offers
                """)).fetchone()
            win_rate = round((int(d[2] or 0) / int(d[3] or 1)) * 100) if d[3] else 0
            return dict(
                total_leads=int(l[0] or 0), active_leads=int(l[1] or 0),
                total_deals=int(d[0] or 0), pipeline_value=float(d[1] or 0),
                won_deals=int(d[2] or 0), win_rate=win_rate,
                total_offers=int(o[0] or 0), pending_offers=int(o[1] or 0)
            )
        except Exception:
            logger.exception("get_sales_summary failed")
            return dict(total_leads=0,active_leads=0,total_deals=0,pipeline_value=0,
                        won_deals=0,win_rate=0,total_offers=0,pending_offers=0)

    def get_sales_leads(self, status=None, source=None):
        try:
            q = "SELECT * FROM sales_leads WHERE 1=1"
            params = {}
            if status and status != "All":
                q += " AND status=:status"; params["status"] = status
            if source and source != "All":
                q += " AND source=:source"; params["source"] = source
            q += " ORDER BY created_at DESC"
            return self.fetch_dataframe(q, params)
        except Exception:
            logger.exception("get_sales_leads failed")
            return None

    def add_lead(self, lead_name, company_name, email, phone, country, source,
                 freight_interest, notes, assigned_to_id=None):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO sales_leads
                        (lead_name,company_name,email,phone,country,source,status,
                         freight_interest,notes,assigned_to_id)
                    VALUES (:ln,:cn,:em,:ph,:co,:src,'New',:fi,:nt,:atid)
                """), dict(ln=lead_name,cn=company_name,em=email,ph=phone,co=country,
                           src=source,fi=freight_interest,nt=notes,atid=assigned_to_id))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_lead failed")
            return False

    def update_lead_status(self, lead_id, status):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE sales_leads SET status=:s WHERE id=:id"), {"s":status,"id":lead_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_lead_status failed")
            return False

    def get_sales_deals(self, stage=None):
        try:
            q = "SELECT * FROM sales_deals WHERE 1=1"
            params = {}
            if stage and stage != "All":
                q += " AND stage=:stage"; params["stage"] = stage
            q += " ORDER BY created_at DESC"
            return self.fetch_dataframe(q, params)
        except Exception:
            logger.exception("get_sales_deals failed")
            return None

    def add_deal(self, title, client_name, value, currency, stage, probability,
                 close_date, freight_type, origin, destination, notes,
                 lead_id=None, assigned_to_id=None):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO sales_deals
                        (lead_id,title,client_name,value,currency,stage,probability,
                         close_date,freight_type,origin,destination,notes,assigned_to_id)
                    VALUES (:lid,:t,:cn,:val,:cur,:stg,:prob,:cd,:ft,:org,:dst,:nt,:atid)
                """), dict(lid=lead_id,t=title,cn=client_name,val=value,cur=currency,
                           stg=stage,prob=probability,cd=close_date,ft=freight_type,
                           org=origin,dst=destination,nt=notes,atid=assigned_to_id))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_deal failed")
            return False

    def update_deal_stage(self, deal_id, stage, probability=None):
        try:
            with self.get_connection() as conn:
                if probability is not None:
                    conn.execute(text("UPDATE sales_deals SET stage=:s,probability=:p WHERE id=:id"),
                                 {"s":stage,"p":probability,"id":deal_id})
                else:
                    conn.execute(text("UPDATE sales_deals SET stage=:s WHERE id=:id"), {"s":stage,"id":deal_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_deal_stage failed")
            return False

    def get_sales_offers(self, status=None):
        try:
            q = "SELECT * FROM sales_offers WHERE 1=1"
            params = {}
            if status and status != "All":
                q += " AND status=:status"; params["status"] = status
            q += " ORDER BY created_at DESC"
            return self.fetch_dataframe(q, params)
        except Exception:
            logger.exception("get_sales_offers failed")
            return None

    def add_offer(self, offer_number, client_name, client_email, freight_type, origin,
                  destination, commodity, weight_kg, volume_cbm, total_value, currency,
                  validity_date, notes, created_by, deal_id=None):
        try:
            with self.get_connection() as conn:
                conn.execute(text("""
                    INSERT INTO sales_offers
                        (offer_number,deal_id,client_name,client_email,freight_type,
                         origin,destination,commodity,weight_kg,volume_cbm,total_value,
                         currency,validity_date,status,notes,created_by)
                    VALUES (:on,:did,:cn,:ce,:ft,:org,:dst,:com,:wt,:vol,:tv,:cur,:vd,'Draft',:nt,:cb)
                """), dict(on=offer_number,did=deal_id,cn=client_name,ce=client_email,
                           ft=freight_type,org=origin,dst=destination,com=commodity,
                           wt=weight_kg,vol=volume_cbm,tv=total_value,cur=currency,
                           vd=validity_date,nt=notes,cb=created_by))
                conn.commit()
            return True
        except Exception:
            logger.exception("add_offer failed")
            return False

    def update_offer_status(self, offer_id, status):
        try:
            with self.get_connection() as conn:
                conn.execute(text("UPDATE sales_offers SET status=:s WHERE id=:id"), {"s":status,"id":offer_id})
                conn.commit()
            return True
        except Exception:
            logger.exception("update_offer_status failed")
            return False
