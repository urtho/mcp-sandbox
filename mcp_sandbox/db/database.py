import os
import sqlite3
from typing import Dict, List, Optional
import uuid
from datetime import datetime


class Database:
    """SQLite-based database for user authentication and sandboxes"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "sandbox.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_db()

    def _initialize_db(self):
        cur = self.conn.cursor()
        # Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                hashed_password TEXT,
                created_at TEXT,
                is_active INTEGER,
                api_key TEXT
            )
        """)
        # Sandboxes table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sandboxes (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                name TEXT,
                created_at TEXT,
                docker_container_id TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        self.conn.commit()

    def get_user(
        self, username: str = None, email: str = None, user_id: str = None
    ) -> Optional[Dict]:
        """Get user by username, email or ID"""
        try:
            cur = self.conn.cursor()
            if username:
                cur.execute(
                    "SELECT * FROM users WHERE LOWER(username) = ?", (username.lower(),)
                )
            elif email:
                cur.execute(
                    "SELECT * FROM users WHERE LOWER(email) = ?", (email.lower(),)
                )
            elif user_id:
                cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            else:
                return None
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"Error retrieving user: {e}")
            return None

    def create_user(self, user_data: Dict) -> Dict:
        """Create a new user"""
        user_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        is_active = 1
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO users (id, username, email, hashed_password, created_at, is_active, api_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                user_id,
                user_data.get("username"),
                user_data.get("email"),
                user_data.get("hashed_password"),
                created_at,
                is_active,
                user_data.get("api_key"),
            ),
        )
        self.conn.commit()
        return {
            "id": user_id,
            "username": user_data.get("username"),
            "email": user_data.get("email"),
            "hashed_password": user_data.get("hashed_password"),
            "created_at": created_at,
            "is_active": True,
            "api_key": user_data.get("api_key"),
        }

    def update_user(self, user_id: str, user_data: Dict) -> Optional[Dict]:
        """Update a user"""
        cur = self.conn.cursor()
        fields = []
        values = []
        for k, v in user_data.items():
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(user_id)
        sql = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"
        cur.execute(sql, tuple(values))
        self.conn.commit()
        return self.get_user(user_id=user_id)

    def get_all_users(self) -> List[Dict]:
        """Get all users"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM users")
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_user_by_api_key(self, api_key: str) -> Optional[Dict]:
        """Get user by API key

        Args:
            api_key: The API key to lookup

        Returns:
            User dict if API key is valid, None otherwise
        """
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM users WHERE api_key = ?", (api_key,))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"Error retrieving user by API key: {e}")
            return None

    def create_sandbox(
        self, user_id: str, name: str = None, docker_container_id: str = None
    ) -> str:
        """Create a new sandbox for a user"""
        sandbox_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        if name is None:
            # Count user's sandboxes
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sandboxes WHERE user_id = ?", (user_id,))
            count = cur.fetchone()[0]
            name = f"Sandbox {count + 1}"
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO sandboxes (id, user_id, name, created_at, docker_container_id)
            VALUES (?, ?, ?, ?, ?)
        """,
            (sandbox_id, user_id, name, created_at, docker_container_id),
        )
        self.conn.commit()
        return sandbox_id

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict]:
        """Get sandbox by ID"""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM sandboxes WHERE id = ?", (sandbox_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"Error retrieving sandbox: {e}")
            return None

    def get_user_sandboxes(self, user_id: str) -> List[Dict]:
        """Get all sandboxes for a user"""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM sandboxes WHERE user_id = ?", (user_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"Error retrieving user sandboxes: {e}")
            return []

    def is_sandbox_owner(self, user_id: str, sandbox_id: str) -> bool:
        """Check if a user owns a sandbox"""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False
        return sandbox.get("user_id") == user_id

    def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox by ID"""
        try:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM sandboxes WHERE id = ?", (sandbox_id,))
            self.conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"Error deleting sandbox: {e}")
            return False

    def delete_sandbox_by_container_id(self, docker_container_id: str) -> bool:
        """Delete a sandbox row by its Docker container ID"""
        try:
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM sandboxes WHERE docker_container_id = ?",
                (docker_container_id,),
            )
            self.conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"Error deleting sandbox by container id: {e}")
            return False


# Create global instance
db = Database()
