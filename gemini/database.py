import sqlite3
import logging
from datetime import datetime
import hashlib


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all database interactions for user data."""

    def __init__(self, db_name="user_data.db"):
        """Initializes the database connection and creates tables if they don't exist."""
        try:
            self.conn = sqlite3.connect(db_name, check_same_thread=False)
            self.cursor = self.conn.cursor()
            self.create_tables()
            logger.info(f"Database '{db_name}' initialized and tables are ready.")
        except sqlite3.Error as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def create_tables(self):
        """Creates the necessary tables for chat history, feedback, summaries, users and chat-specific summaries.

        Notes:
            - Adds a new `users` table to store signup info.
            - Adds a new `chat_summaries` table to store per-chat summaries (chat_id scoped) while
              the existing `user_summaries` table continues to hold global summaries (e.g. feedback).
            - If legacy tables exist without new columns, they are left untouched for backward compatibility.
        """
        try:
            # Table for individual chat messages
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """)

            # Table for user feedback
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    feedback_text TEXT NOT NULL
                )
            """)

            # Table for storing summaries
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_summaries (
                    user_id TEXT NOT NULL,
                    summary_type TEXT NOT NULL,
                    summary_text TEXT,
                    last_updated DATETIME NOT NULL,
                    PRIMARY KEY (user_id, summary_type)
                )
            """)

            # NEW: Table for storing per-chat summaries (chat scoped)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_summaries (
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    summary_type TEXT NOT NULL,
                    summary_text TEXT,
                    last_updated DATETIME NOT NULL,
                    PRIMARY KEY (user_id, chat_id, summary_type)
                )
            """)

            # NEW: Users table for signup information
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
            """)
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error creating tables: {e}")
            self.conn.rollback()
            raise

    def add_chat_history(self, user_id: str, chat_id: str, messages: list[dict]):
        """Adds a list of chat messages to the database under a specific chat_id."""
        try:
            records = [
                (user_id, chat_id, datetime.now(), msg.get("role", "unknown"), msg.get("content", ""))
                for msg in messages
            ]
            self.cursor.executemany(
                "INSERT INTO chat_history (user_id, chat_id, timestamp, role, content) VALUES (?, ?, ?, ?, ?)",
                records
            )
            self.conn.commit()
            logger.info(f"Added {len(records)} chat messages for user '{user_id}' in chat '{chat_id}'.")
        except sqlite3.Error as e:
            logger.error(f"Error adding chat history for user '{user_id}' chat '{chat_id}': {e}")
            self.conn.rollback()
            raise

    def add_feedback(self, user_id: str, feedback_text: str):
        """Adds user feedback to the database."""
        try:
            self.cursor.execute(
                "INSERT INTO feedback (user_id, timestamp, feedback_text) VALUES (?, ?, ?)",
                (user_id, datetime.now(), feedback_text)
            )
            self.conn.commit()
            logger.info(f"Added feedback for user '{user_id}'.")
        except sqlite3.Error as e:
            logger.error(f"Error adding feedback for user '{user_id}': {e}")
            self.conn.rollback()
            raise

    def get_recent_history(self, user_id: str, chat_id: str, limit: int = 20) -> list[dict]:
        """Retrieves the most recent chat history for a user for a specific chat_id."""
        try:
            self.cursor.execute(
                "SELECT role, content FROM chat_history WHERE user_id = ? AND chat_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, chat_id, limit)
            )
            rows = self.cursor.fetchall()
            # Return in chronological order for displaying in the chat window
            return [{"role": role, "content": content} for role, content in reversed(rows)]
        except sqlite3.Error as e:
            logger.error(f"Error getting chat history for user '{user_id}', chat '{chat_id}': {e}")
            return []
    def get_chat_list(self, user_id: str) -> list[dict]:
        """
        Retrieves the list of all chats for a user, with a dynamically generated title
        and the last message's timestamp for sorting.
        """
        try:
            self.cursor.execute(
                """
                SELECT
                    chat_id,
                    MAX(timestamp) as last_updated,
                    (
                        SELECT content
                        FROM chat_history h2
                        WHERE h2.chat_id = h1.chat_id AND h2.role = 'user'
                        ORDER BY h2.timestamp ASC
                        LIMIT 1
                    ) as title
                FROM chat_history h1
                WHERE user_id = ?
                GROUP BY chat_id
                ORDER BY last_updated DESC
                """,
                (user_id,)
            )
            rows = self.cursor.fetchall()
            
            chat_list = []
            for row in rows:
                chat_id, last_updated, title = row
                
                if not title:
                    title = "Untitled Chat" # Fallback if no user message
                else:
                    # Truncate title for display
                    title = (title[:40] + '...') if len(title) > 43 else title 
                
                chat_list.append({
                    "id": chat_id,
                    "timestamp": last_updated,
                    "title": title
                })
            return chat_list
        except sqlite3.Error as e:
            logger.error(f"Error getting chat list for user '{user_id}': {e}")
            return []
    
    def get_recent_feedback(self, user_id: str, limit: int = 10) -> list[str]:
        """Retrieves the most recent feedback for a user."""
        try:
            self.cursor.execute(
                "SELECT feedback_text FROM feedback WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            rows = self.cursor.fetchall()
            # Return in chronological order
            return [row[0] for row in reversed(rows)]
        except sqlite3.Error as e:
            logger.error(f"Error getting feedback for user '{user_id}': {e}")
            return []

    def get_summary(self, user_id: str, summary_type: str, chat_id: str | None = None) -> str | None:
        """Retrieves the latest summary for a user and type.

        For summary_type == 'chat', a chat_id is expected. If provided, it will fetch from chat_summaries.
        For other summary types (e.g., 'feedback'), falls back to user_summaries.
        """
        try:
            if summary_type == "chat" and chat_id:
                self.cursor.execute(
                    "SELECT summary_text FROM chat_summaries WHERE user_id = ? AND chat_id = ? AND summary_type = ?",
                    (user_id, chat_id, summary_type)
                )
                result = self.cursor.fetchone()
                return result[0] if result else None
            else:
                self.cursor.execute(
                    "SELECT summary_text FROM user_summaries WHERE user_id = ? AND summary_type = ?",
                    (user_id, summary_type)
                )
                result = self.cursor.fetchone()
                return result[0] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error getting summary for user '{user_id}': {e}")
            return None

    def update_summary(self, user_id: str, summary_type: str, new_summary: str):
        """Updates or inserts a summary for a user."""
        try:
            self.cursor.execute(
                """
                INSERT INTO user_summaries (user_id, summary_type, summary_text, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, summary_type) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    last_updated = excluded.last_updated
                """,
                (user_id, summary_type, new_summary, datetime.now())
            )
            self.conn.commit()
            logger.info(f"Updated '{summary_type}' summary for user '{user_id}'.")
        except sqlite3.Error as e:
            logger.error(f"Error updating summary for user '{user_id}': {e}")
            self.conn.rollback()
            raise

    # NEW: Chat-scoped summary update
    def update_chat_summary(self, user_id: str, chat_id: str, summary_type: str, new_summary: str):
        try:
            self.cursor.execute(
                """
                INSERT INTO chat_summaries (user_id, chat_id, summary_type, summary_text, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, chat_id, summary_type) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    last_updated = excluded.last_updated
                """,
                (user_id, chat_id, summary_type, new_summary, datetime.now())
            )
            self.conn.commit()
            logger.info(f"Updated chat '{chat_id}' '{summary_type}' summary for user '{user_id}'.")
        except sqlite3.Error as e:
            logger.error(f"Error updating chat summary for user '{user_id}' chat '{chat_id}': {e}")
            self.conn.rollback()
            raise
    
    # NEW: Function to delete a chat
    def delete_chat(self, user_id: str, chat_id: str):
        """Deletes all data associated with a specific chat_id for a user."""
        try:
            # Delete messages from chat_history
            self.cursor.execute(
                "DELETE FROM chat_history WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id)
            )
            
            # Delete summary from chat_summaries
            self.cursor.execute(
                "DELETE FROM chat_summaries WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id)
            )
            
            self.conn.commit()
            logger.info(f"Deleted chat '{chat_id}' for user '{user_id}'.")
        except sqlite3.Error as e:
            logger.error(f"Error deleting chat '{chat_id}' for user '{user_id}': {e}")
            self.conn.rollback()
            raise

    # ========== USER MANAGEMENT ==========
    def add_user(self, username: str, email: str, password: str):
        """Registers a new user. Password is stored as SHA256 hash (note: not for production)."""
        try:
            password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
            self.cursor.execute(
                "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (username, email, password_hash, datetime.now())
            )
            self.conn.commit()
            logger.info(f"User '{username}' registered.")
        except sqlite3.IntegrityError:
            raise ValueError("Username or email already exists")
        except sqlite3.Error as e:
            logger.error(f"Error adding user '{username}': {e}")
            self.conn.rollback()
            raise

    def user_exists(self, username: str) -> bool:
        self.cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        return self.cursor.fetchone() is not None

    def validate_user(self, username: str, password: str) -> bool:
        password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
        self.cursor.execute(
            "SELECT 1 FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        return self.cursor.fetchone() is not None

    def get_user_email(self, username: str) -> str | None:
        self.cursor.execute("SELECT email FROM users WHERE username = ?", (username,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def __del__(self):
        """Ensures the database connection is closed on object deletion."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

# Singleton instance to be used across the application
db_manager = DatabaseManager()
