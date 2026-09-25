import sqlite3
import threading
from typing import List, Optional


class Database:
    """
    Класс для работы с базой данных SQLite.

    Таблицы:
        rooms         - комнаты (id, secret_key, status, created_at)
        room_members  - участники комнат (room_id, user_id, joined_at)
        queue         - очередь случайного подбора собеседника (user_id, joined_at)
        users         - все пользователи, когда-либо писавшие боту
                        (user_id, username, first_seen, last_seen)

    Комната может содержать более двух участников. Комната закрывается
    полностью только тогда, когда после выхода одного из участников
    в ней остаётся ровно один человек (либо ноль).
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    secret_key TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'waiting',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS room_members (
                    room_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (room_id, user_id),
                    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    user_id INTEGER PRIMARY KEY,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    # ---------------------------------------------------------------- users

    def upsert_user(self, user_id: int, username: Optional[str]) -> None:
        """Сохраняет/обновляет запись о пользователе, писавшем боту."""
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_seen, last_seen)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (user_id, username),
            )
            conn.commit()

    def find_user_by_username(self, username: str) -> Optional[int]:
        username = username.lstrip("@")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT user_id FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            )
            row = cur.fetchone()
            return row["user_id"] if row else None

    def user_known(self, user_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return cur.fetchone() is not None

    # ---------------------------------------------------------------- rooms

    def key_exists(self, secret_key: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT 1 FROM rooms WHERE secret_key = ?", (secret_key,)
            )
            return cur.fetchone() is not None

    def create_room(self, secret_key: str, creator_id: int) -> bool:
        """Создаёт комнату со статусом 'waiting' и добавляет создателя как участника."""
        with self._lock, self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO rooms (secret_key, status) VALUES (?, 'waiting')",
                    (secret_key,),
                )
                room_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)",
                    (room_id, creator_id),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def create_room_with_members(self, secret_key: str, user_ids: List[int]) -> int:
        """Создаёт активную комнату сразу с несколькими участниками (для подбора). Возвращает room_id."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO rooms (secret_key, status) VALUES (?, 'active')",
                (secret_key,),
            )
            room_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)",
                [(room_id, uid) for uid in user_ids],
            )
            conn.commit()
            return room_id

    def get_room_by_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                SELECT rooms.* FROM rooms
                JOIN room_members ON room_members.room_id = rooms.id
                WHERE room_members.user_id = ?
                """,
                (user_id,),
            )
            return cur.fetchone()

    def get_members(self, room_id: int) -> List[int]:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT user_id FROM room_members WHERE room_id = ?", (room_id,)
            )
            return [row["user_id"] for row in cur.fetchall()]

    def get_other_members(self, user_id: int) -> List[int]:
        """Возвращает id всех остальных участников комнаты пользователя (если он в комнате)."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                SELECT room_members.user_id FROM room_members
                WHERE room_id = (
                    SELECT room_id FROM room_members WHERE user_id = ?
                ) AND user_id != ?
                """,
                (user_id, user_id),
            )
            return [row["user_id"] for row in cur.fetchall()]

    def join_room(self, secret_key: str, user_id: int) -> Optional[List[int]]:
        """
        Присоединяет пользователя к комнате по ключу (комната может уже
        быть активной — присоединиться могут более двух человек).
        Возвращает список id участников, уже находившихся в комнате
        (для уведомления), либо None, если ключ не найден или
        пользователь уже состоит в этой комнате.
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM rooms WHERE secret_key = ?", (secret_key,)
            )
            room = cur.fetchone()
            if room is None:
                return None

            cur = conn.execute(
                "SELECT user_id FROM room_members WHERE room_id = ?", (room["id"],)
            )
            existing_members = [row["user_id"] for row in cur.fetchall()]

            if user_id in existing_members:
                return None

            conn.execute(
                "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)",
                (room["id"], user_id),
            )
            conn.execute(
                "UPDATE rooms SET status = 'active' WHERE id = ?", (room["id"],)
            )
            conn.commit()
            return existing_members

    def leave_room(self, user_id: int) -> Optional[dict]:
        """
        Убирает пользователя из его комнаты.
        Возвращает словарь:
            {"remaining": [...], "closed": bool}
        remaining - id участников, оставшихся в комнате (может быть пуст).
        closed = True, если комната была полностью закрыта — это происходит,
        когда после выхода в комнате остаётся не более одного человека
        (то есть чат прерывается только тогда, когда участник остаётся один).
        Возвращает None, если пользователь не состоял ни в одной комнате.
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT room_id FROM room_members WHERE user_id = ?", (user_id,)
            )
            row = cur.fetchone()
            if row is None:
                return None

            room_id = row["room_id"]
            conn.execute(
                "DELETE FROM room_members WHERE room_id = ? AND user_id = ?",
                (room_id, user_id),
            )

            cur = conn.execute(
                "SELECT user_id FROM room_members WHERE room_id = ?", (room_id,)
            )
            remaining = [r["user_id"] for r in cur.fetchall()]

            closed = False
            if len(remaining) <= 1:
                conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
                closed = True

            conn.commit()
            return {"remaining": remaining, "closed": closed}

    def is_user_in_room(self, user_id: int) -> bool:
        return self.get_room_by_user(user_id) is not None

    def is_room_active(self, user_id: int) -> bool:
        room = self.get_room_by_user(user_id)
        return room is not None and room["status"] == "active"

    # ---------------------------------------------------------------- queue

    def queue_add(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO queue (user_id) VALUES (?)", (user_id,)
            )
            conn.commit()

    def queue_remove(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))
            conn.commit()

    def queue_contains(self, user_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("SELECT 1 FROM queue WHERE user_id = ?", (user_id,))
            return cur.fetchone() is not None

    def queue_pop_any(self, exclude_user_id: int) -> Optional[int]:
        """Достаёт из очереди самого давно ожидающего пользователя (кроме exclude_user_id)."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT user_id FROM queue WHERE user_id != ? ORDER BY joined_at ASC LIMIT 1",
                (exclude_user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM queue WHERE user_id = ?", (row["user_id"],))
            conn.commit()
            return row["user_id"]
