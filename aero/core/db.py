"""Base de datos local (SQLite + FTS5): biblioteca, historial, favoritos, listas y posiciones.

Cada hilo debe abrir su propia instancia de `Database` (las conexiones SQLite no se comparten).
Nunca se modifican los archivos del usuario: solo se guardan rutas y metadatos.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from aero.core.paths import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS media(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    root TEXT, folder TEXT, name TEXT, ext TEXT, kind TEXT,
    size INTEGER, mtime REAL,
    title TEXT, artist TEXT, album TEXT, album_artist TEXT, genre TEXT,
    year INTEGER, track INTEGER, duration REAL, added_at REAL
);
CREATE INDEX IF NOT EXISTS ix_media_kind ON media(kind);
CREATE INDEX IF NOT EXISTS ix_media_album ON media(album);
CREATE INDEX IF NOT EXISTS ix_media_artist ON media(artist);
CREATE INDEX IF NOT EXISTS ix_media_folder ON media(folder);
CREATE INDEX IF NOT EXISTS ix_media_root ON media(root);
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    name, title, artist, album, content='media', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS media_ai AFTER INSERT ON media BEGIN
    INSERT INTO media_fts(rowid, name, title, artist, album) VALUES (new.id, new.name, new.title, new.artist, new.album);
END;
CREATE TRIGGER IF NOT EXISTS media_ad AFTER DELETE ON media BEGIN
    INSERT INTO media_fts(media_fts, rowid, name, title, artist, album) VALUES ('delete', old.id, old.name, old.title, old.artist, old.album);
END;
CREATE TRIGGER IF NOT EXISTS media_au AFTER UPDATE ON media BEGIN
    INSERT INTO media_fts(media_fts, rowid, name, title, artist, album) VALUES ('delete', old.id, old.name, old.title, old.artist, old.album);
    INSERT INTO media_fts(rowid, name, title, artist, album) VALUES (new.id, new.name, new.title, new.artist, new.album);
END;
CREATE TABLE IF NOT EXISTS recents(path TEXT PRIMARY KEY, kind TEXT, opened_at REAL);
CREATE TABLE IF NOT EXISTS played(path TEXT PRIMARY KEY, title TEXT, artist TEXT, played_at REAL, count INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS favorites(path TEXT PRIMARY KEY, added_at REAL);
CREATE TABLE IF NOT EXISTS playlists(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS playlist_items(
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position INTEGER NOT NULL, path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pl_items ON playlist_items(playlist_id, position);
CREATE TABLE IF NOT EXISTS positions(path TEXT PRIMARY KEY, position_ms INTEGER, updated_at REAL);
CREATE TABLE IF NOT EXISTS watched(path TEXT PRIMARY KEY, watched_at REAL);
-- Personalización visual de álbumes dentro de AERO Player (nunca se escribe en los archivos).
CREATE TABLE IF NOT EXISTS album_info(album TEXT PRIMARY KEY, title TEXT, artist TEXT, cover TEXT, updated_at REAL);
-- Archivos retirados de la biblioteca por el usuario: el escáner no los vuelve a añadir.
CREATE TABLE IF NOT EXISTS hidden(path TEXT PRIMARY KEY, hidden_at REAL);
-- Biblioteca «Archivos»: referencias a carpetas del equipo y su aspecto en AERO Player (nunca se tocan).
CREATE TABLE IF NOT EXISTS folders(
    path TEXT PRIMARY KEY, title TEXT, description TEXT, cover TEXT, color TEXT,
    favorite INTEGER DEFAULT 0, position INTEGER DEFAULT 0, sort TEXT, added_at REAL
);
"""

SORT_COLUMNS = {
    "title": ("COALESCE(NULLIF(title,''), name) COLLATE NOCASE",),
    "artist": ("artist COLLATE NOCASE", "album COLLATE NOCASE", "track"),
    "album": ("album COLLATE NOCASE", "track"),
    "duration": ("duration",),
    "size": ("size",),
    "mtime": ("mtime",),
    "name": ("name COLLATE NOCASE",),
    "added": ("added_at",),
    "kind": ("ext",),
}

MAX_RECENTS = 200


def fts_query(text: str) -> str:
    """Convierte texto libre en una consulta FTS5 segura (prefijos, AND implícito)."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if t]
    return " ".join(f'"{t}"*' for t in tokens)


def _order_by(order: str, desc: bool) -> str:
    direction = "DESC" if desc else "ASC"
    cols = SORT_COLUMNS.get(order, SORT_COLUMNS["title"])
    return ", ".join(f"{c} {direction}" for c in cols) + ", id ASC"


class Database:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "library.db"
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- biblioteca
    def upsert_media(self, rows: list[dict]) -> None:
        if not rows:
            return
        now = time.time()
        cols = ("path", "root", "folder", "name", "ext", "kind", "size", "mtime", "title", "artist", "album",
                "album_artist", "genre", "year", "track", "duration")
        sql = (
            f"INSERT INTO media({','.join(cols)}, added_at) VALUES ({','.join('?' * len(cols))}, ?) "
            "ON CONFLICT(path) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in cols[1:])
        )
        self.conn.executemany(sql, [tuple(r.get(c) for c in cols) + (now,) for r in rows])
        self.conn.commit()

    def known_files(self, root: str) -> dict[str, tuple[float, int]]:
        cur = self.conn.execute("SELECT path, mtime, size FROM media WHERE root=?", (root,))
        return {r["path"]: (r["mtime"], r["size"]) for r in cur}

    def remove_paths(self, paths: list[str]) -> None:
        self.conn.executemany("DELETE FROM media WHERE path=?", [(p,) for p in paths])
        self.conn.commit()

    def remove_root(self, root: str) -> None:
        self.conn.execute("DELETE FROM media WHERE root=?", (root,))
        self.conn.commit()

    def _filters(self, kind=None, search="", album=None, artist=None, folder=None):
        where, args = [], []
        if kind:
            where.append("kind=?")
            args.append(kind)
        if album is not None:
            where.append("COALESCE(album,'')=?")
            args.append(album)
        if artist is not None:
            where.append("COALESCE(NULLIF(album_artist,''), artist, '')=?")
            args.append(artist)
        if folder is not None:
            where.append("folder=?")
            args.append(folder)
        q = fts_query(search) if search else ""
        if q:
            where.append("id IN (SELECT rowid FROM media_fts WHERE media_fts MATCH ?)")
            args.append(q)
        return (" WHERE " + " AND ".join(where)) if where else "", args

    def query_media(self, kind=None, search="", album=None, artist=None, folder=None,
                    order="title", desc=False, limit=300, offset=0) -> list[sqlite3.Row]:
        where, args = self._filters(kind, search, album, artist, folder)
        sql = f"SELECT * FROM media{where} ORDER BY {_order_by(order, desc)} LIMIT ? OFFSET ?"
        return self.conn.execute(sql, (*args, limit, offset)).fetchall()

    def count_media(self, kind=None, search="", album=None, artist=None, folder=None) -> int:
        where, args = self._filters(kind, search, album, artist, folder)
        return self.conn.execute(f"SELECT COUNT(*) FROM media{where}", args).fetchone()[0]

    def all_paths(self, kind=None, search="", album=None, artist=None, folder=None, order="title", desc=False) -> list[str]:
        where, args = self._filters(kind, search, album, artist, folder)
        return [r[0] for r in self.conn.execute(f"SELECT path FROM media{where} ORDER BY {_order_by(order, desc)}", args)]

    def albums(self, search="") -> list[sqlite3.Row]:
        where, args = self._filters("audio", search)
        return self.conn.execute(
            f"SELECT COALESCE(album,'') AS album, COALESCE(NULLIF(MAX(album_artist),''), MAX(artist), '') AS artist, "
            f"COUNT(*) AS n, SUM(duration) AS duration, MIN(path) AS sample FROM media{where} "
            "GROUP BY COALESCE(album,'') ORDER BY album COLLATE NOCASE", args).fetchall()

    # ---------------------------------------------------------------- álbumes personalizados
    def album_info(self, album: str) -> dict:
        r = self.conn.execute("SELECT title, artist, cover FROM album_info WHERE album=?", (album,)).fetchone()
        return {"title": r[0] or "", "artist": r[1] or "", "cover": r[2] or ""} if r else {}

    def album_infos(self) -> dict[str, dict]:
        return {r[0]: {"title": r[1] or "", "artist": r[2] or "", "cover": r[3] or ""}
                for r in self.conn.execute("SELECT album, title, artist, cover FROM album_info")}

    def set_album_info(self, album: str, title: str = "", artist: str = "", cover: str = "") -> None:
        if not (title or artist or cover):
            self.conn.execute("DELETE FROM album_info WHERE album=?", (album,))
        else:
            self.conn.execute("INSERT OR REPLACE INTO album_info(album, title, artist, cover, updated_at) "
                              "VALUES (?,?,?,?,?)", (album, title, artist, cover, time.time()))
        self.conn.commit()

    def album_details(self, album: str) -> dict:
        r = self.conn.execute(
            "SELECT COUNT(*), SUM(duration), SUM(size), MIN(year), MAX(year), GROUP_CONCAT(DISTINCT genre), "
            "GROUP_CONCAT(DISTINCT ext), COUNT(DISTINCT folder), MIN(folder) "
            "FROM media WHERE kind='audio' AND COALESCE(album,'')=?", (album,)).fetchone()
        return {"tracks": r[0] or 0, "duration": r[1] or 0, "size": r[2] or 0, "year_min": r[3], "year_max": r[4],
                "genres": r[5] or "", "formats": r[6] or "", "folders": r[7] or 0, "folder": r[8] or ""}

    # ---------------------------------------------------------------- biblioteca de carpetas
    FOLDER_FIELDS = ("title", "description", "cover", "color", "favorite", "sort")

    def library_folders(self) -> list[dict]:
        """Carpetas de la biblioteca «Archivos» en el orden elegido (las favoritas se filtran aparte)."""
        rows = self.conn.execute("SELECT path, title, description, cover, color, favorite, position, sort, added_at "
                                 "FROM folders ORDER BY position, added_at").fetchall()
        keys = ("path", "title", "description", "cover", "color", "favorite", "position", "sort", "added_at")
        return [{k: (v if v is not None else ("" if k not in ("favorite", "position") else 0))
                 for k, v in zip(keys, r)} for r in rows]

    def add_folder(self, path: str) -> bool:
        """Añade la referencia (al final). Devuelve False si ya estaba."""
        if self.conn.execute("SELECT 1 FROM folders WHERE path=?", (path,)).fetchone():
            return False
        pos = (self.conn.execute("SELECT MAX(position) FROM folders").fetchone()[0] or 0) + 1
        self.conn.execute("INSERT INTO folders(path, position, added_at) VALUES (?,?,?)", (path, pos, time.time()))
        self.conn.commit()
        return True

    def update_folder(self, path: str, **fields) -> None:
        cols = {k: v for k, v in fields.items() if k in self.FOLDER_FIELDS}
        if not cols:
            return
        sets = ", ".join(f"{k}=?" for k in cols)
        self.conn.execute(f"UPDATE folders SET {sets} WHERE path=?", (*cols.values(), path))
        self.conn.commit()

    def remove_folder(self, path: str) -> None:
        """Solo quita la referencia: la carpeta y su contenido no se tocan."""
        self.conn.execute("DELETE FROM folders WHERE path=?", (path,))
        self.conn.commit()

    def reorder_folders(self, paths: list[str]) -> None:
        self.conn.executemany("UPDATE folders SET position=? WHERE path=?", [(i, p) for i, p in enumerate(paths)])
        self.conn.commit()

    # ---------------------------------------------------------------- retirar de la biblioteca
    def hide_paths(self, paths: list[str]) -> None:
        """Retira archivos de la biblioteca sin tocarlos en el disco; el escáner no los vuelve a añadir."""
        now = time.time()
        self.conn.executemany("INSERT OR REPLACE INTO hidden(path, hidden_at) VALUES (?,?)", [(p, now) for p in paths])
        self.conn.executemany("DELETE FROM media WHERE path=?", [(p,) for p in paths])
        self.conn.commit()

    def hidden_paths(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT path FROM hidden")}

    def unhide_all(self) -> None:
        self.conn.execute("DELETE FROM hidden")
        self.conn.commit()

    def artists(self, search="") -> list[sqlite3.Row]:
        where, args = self._filters("audio", search)
        return self.conn.execute(
            f"SELECT COALESCE(NULLIF(album_artist,''), artist, '') AS artist, COUNT(*) AS n, "
            f"COUNT(DISTINCT album) AS albums FROM media{where} GROUP BY 1 ORDER BY 1 COLLATE NOCASE", args).fetchall()

    def folders(self, search="") -> list[sqlite3.Row]:
        where, args = self._filters(None, search)
        return self.conn.execute(
            f"SELECT folder, COUNT(*) AS n FROM media{where} GROUP BY folder ORDER BY folder COLLATE NOCASE", args).fetchall()

    def media_by_path(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM media WHERE path=?", (path,)).fetchone()

    def library_stats(self) -> dict:
        r = self.conn.execute(
            "SELECT SUM(kind='audio'), SUM(kind='video'), SUM(duration), SUM(size) FROM media").fetchone()
        return {"audio": r[0] or 0, "video": r[1] or 0, "duration": r[2] or 0, "size": r[3] or 0}

    # ---------------------------------------------------------------- historial
    def add_recent(self, path: str, kind: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO recents(path, kind, opened_at) VALUES (?,?,?)", (path, kind, time.time()))
        self.conn.execute(
            "DELETE FROM recents WHERE path NOT IN (SELECT path FROM recents ORDER BY opened_at DESC LIMIT ?)",
            (MAX_RECENTS,))
        self.conn.commit()

    def recents(self, limit=30) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM recents ORDER BY opened_at DESC LIMIT ?", (limit,)).fetchall()

    def add_played(self, path: str, title: str = "", artist: str = "") -> None:
        self.conn.execute(
            "INSERT INTO played(path, title, artist, played_at, count) VALUES (?,?,?,?,1) "
            "ON CONFLICT(path) DO UPDATE SET played_at=excluded.played_at, count=count+1, "
            "title=excluded.title, artist=excluded.artist",
            (path, title, artist, time.time()))
        self.conn.execute(
            "DELETE FROM played WHERE path NOT IN (SELECT path FROM played ORDER BY played_at DESC LIMIT ?)",
            (MAX_RECENTS,))
        self.conn.commit()

    def recently_played(self, limit=30) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM played ORDER BY played_at DESC LIMIT ?", (limit,)).fetchall()

    def clear_history(self) -> None:
        self.conn.executescript("DELETE FROM recents; DELETE FROM played; DELETE FROM positions; DELETE FROM watched;")
        self.conn.commit()

    def clear_all(self) -> None:
        self.conn.executescript(
            "DELETE FROM recents; DELETE FROM played; DELETE FROM positions; DELETE FROM favorites; DELETE FROM watched;"
            "DELETE FROM playlist_items; DELETE FROM playlists; DELETE FROM media; DELETE FROM album_info;"
            "DELETE FROM hidden; DELETE FROM folders;")
        self.conn.commit()

    # ---------------------------------------------------------------- favoritos
    def is_favorite(self, path: str) -> bool:
        return self.conn.execute("SELECT 1 FROM favorites WHERE path=?", (path,)).fetchone() is not None

    def set_favorite(self, path: str, fav: bool) -> None:
        if fav:
            self.conn.execute("INSERT OR IGNORE INTO favorites(path, added_at) VALUES (?,?)", (path, time.time()))
        else:
            self.conn.execute("DELETE FROM favorites WHERE path=?", (path,))
        self.conn.commit()

    def favorites(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT path FROM favorites ORDER BY added_at DESC")]

    # ---------------------------------------------------------------- listas
    def playlists(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id=p.id) AS n "
            "FROM playlists p ORDER BY name COLLATE NOCASE").fetchall()

    def create_playlist(self, name: str, paths: list[str] | None = None) -> int:
        now = time.time()
        cur = self.conn.execute("INSERT INTO playlists(name, created_at, updated_at) VALUES (?,?,?)", (name, now, now))
        pid = cur.lastrowid
        if paths:
            self.set_playlist_items(pid, paths)
        self.conn.commit()
        return pid

    def rename_playlist(self, pid: int, name: str) -> None:
        self.conn.execute("UPDATE playlists SET name=?, updated_at=? WHERE id=?", (name, time.time(), pid))
        self.conn.commit()

    def delete_playlist(self, pid: int) -> None:
        self.conn.execute("DELETE FROM playlists WHERE id=?", (pid,))
        self.conn.commit()

    def playlist_items(self, pid: int) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT path FROM playlist_items WHERE playlist_id=? ORDER BY position", (pid,))]

    def set_playlist_items(self, pid: int, paths: list[str]) -> None:
        self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
        self.conn.executemany("INSERT INTO playlist_items(playlist_id, position, path) VALUES (?,?,?)",
                              [(pid, i, p) for i, p in enumerate(paths)])
        self.conn.execute("UPDATE playlists SET updated_at=? WHERE id=?", (time.time(), pid))
        self.conn.commit()

    def append_to_playlist(self, pid: int, paths: list[str]) -> None:
        self.set_playlist_items(pid, self.playlist_items(pid) + list(paths))

    # ---------------------------------------------------------------- posiciones
    def save_position(self, path: str, ms: int) -> None:
        if ms <= 0:
            self.conn.execute("DELETE FROM positions WHERE path=?", (path,))
        else:
            self.conn.execute("INSERT OR REPLACE INTO positions(path, position_ms, updated_at) VALUES (?,?,?)",
                              (path, int(ms), time.time()))
        self.conn.commit()

    def mark_watched(self, path: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO watched(path, watched_at) VALUES (?,?)", (path, time.time()))
        self.conn.commit()

    def watched(self, paths: list[str] | None = None) -> set[str]:
        rows = self.conn.execute("SELECT path FROM watched").fetchall()
        got = {r[0] for r in rows}
        return got if paths is None else got.intersection(paths)

    def positions_for(self, paths: list[str]) -> dict[str, int]:
        if not paths:
            return {}
        out = {}
        for i in range(0, len(paths), 500):
            chunk = paths[i:i + 500]
            q = f"SELECT path, position_ms FROM positions WHERE path IN ({','.join('?' * len(chunk))})"
            out.update({r[0]: r[1] for r in self.conn.execute(q, chunk)})
        return out

    def in_progress(self, limit: int = 5) -> list[sqlite3.Row]:
        """Vídeos empezados y no terminados, del más reciente al más antiguo («Continuar viendo»)."""
        return self.conn.execute("SELECT * FROM positions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()

    def position(self, path: str) -> int:
        r = self.conn.execute("SELECT position_ms FROM positions WHERE path=?", (path,)).fetchone()
        return int(r[0]) if r else 0
