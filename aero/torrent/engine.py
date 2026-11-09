"""Motor BitTorrent propio de AERO Player (Python puro, sin dependencias).

Alcance (lo que hace de verdad):
* Trackers HTTP/HTTPS y UDP (BEP 3, 15, 23): anuncio, reanuncio periódico y lista compacta de pares.
* Protocolo de pares (BEP 3): saludo, campo de bits, `have`, interés, choke/unchoke y petición de bloques de
  16 KiB con varias peticiones en vuelo por par; piezas más raras primero y modo final.
* Cada pieza se comprueba con SHA-1 antes de escribirse. Solo se escriben los archivos elegidos; mientras no
  están completos llevan la extensión `.aeropart` y nunca se ejecutan.
* Pausar, reanudar (vuelve a comprobar lo que ya hay en el disco) y cancelar (borra solo los `.aeropart` que creó
  esta descarga).

Fuera de alcance, dicho claramente en la interfaz y en docs/TORRENTS.md: enlaces magnet, DHT e intercambio de pares
(un torrent sin trackers no encuentra pares) y conexiones entrantes (no se abre ningún puerto ni se cambia el
cortafuegos). Por cortesía se responde a las peticiones de los pares a los que estamos conectados.

Todo corre en un bucle `asyncio` en su propio hilo, sin objetos de Qt. La interfaz lee `Download.snapshot()`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from aero.torrent import metainfo

BLOCK = 16 * 1024
PIPELINE = 12
MAX_PEERS = 40
PART = ".aeropart"
PEER_ID = b"-AE2100-" + bytes(random.choice(b"0123456789abcdef") for _ in range(12))
STATES = {"checking": "Comprobando", "connecting": "Buscando pares", "downloading": "Descargando",
          "paused": "En pausa", "done": "Completado", "error": "Error", "cancelled": "Cancelado"}


class EngineError(Exception):
    pass


# ----------------------------------------------------------------------------- trackers

def _compact(peers: bytes) -> list[tuple[str, int]]:
    out = []
    for i in range(0, len(peers) - 5, 6):
        ip = socket.inet_ntoa(peers[i:i + 4])
        port = struct.unpack(">H", peers[i + 4:i + 6])[0]
        if port:
            out.append((ip, port))
    return out


def announce_http(url: str, info_hash: bytes, left: int, downloaded: int, uploaded: int, event: str = "",
                  port: int = 6881, timeout: float = 15) -> tuple[list[tuple[str, int]], int]:
    q = {"info_hash": info_hash, "peer_id": PEER_ID, "port": port, "uploaded": uploaded, "downloaded": downloaded,
         "left": left, "compact": 1, "numwant": 80}
    if event:
        q["event"] = event
    full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    req = urllib.request.Request(full, headers={"User-Agent": "AERO-Player/2.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - tracker del propio torrent
        body = r.read(4 * 1024 * 1024)
    data, _ = metainfo.decode(body)
    if not isinstance(data, dict):
        raise EngineError("Respuesta del tracker no válida.")
    if b"failure reason" in data:
        raise EngineError(metainfo._text(data[b"failure reason"]))
    peers = data.get(b"peers", b"")
    out = _compact(peers) if isinstance(peers, bytes) else [
        (metainfo._text(p.get(b"ip", b"")), int(p.get(b"port", 0))) for p in peers if isinstance(p, dict)]
    return out, int(data.get(b"interval", 1800))


def announce_udp(url: str, info_hash: bytes, left: int, downloaded: int, uploaded: int, event: str = "",
                 port: int = 6881, timeout: float = 8) -> tuple[list[tuple[str, int]], int]:
    u = urllib.parse.urlparse(url)
    addr = (u.hostname, u.port or 80)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        tx = random.getrandbits(32)
        s.sendto(struct.pack(">QII", 0x41727101980, 0, tx), addr)
        resp = s.recv(2048)
        action, rtx, conn = struct.unpack(">IIQ", resp[:16])
        if action != 0 or rtx != tx:
            raise EngineError("El tracker UDP no respondió a la conexión.")
        tx = random.getrandbits(32)
        ev = {"": 0, "completed": 1, "started": 2, "stopped": 3}.get(event, 0)
        s.sendto(struct.pack(">QII20s20sQQQIIIiH", conn, 1, tx, info_hash, PEER_ID, downloaded, left, uploaded, ev,
                             0, random.getrandbits(32), -1, port), addr)
        resp = s.recv(65536)
        action, rtx = struct.unpack(">II", resp[:8])
        if action == 3:
            raise EngineError(resp[8:].decode("utf-8", "replace"))
        if action != 1 or rtx != tx:
            raise EngineError("Respuesta del tracker UDP no válida.")
        interval = struct.unpack(">I", resp[8:12])[0]
        return _compact(resp[20:]), int(interval)
    finally:
        s.close()


def announce(url: str, *a, **k):
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        return announce_http(url, *a, **k)
    if scheme == "udp":
        return announce_udp(url, *a, **k)
    raise EngineError(f"Tipo de tracker no compatible: {scheme}")


# ----------------------------------------------------------------------------- almacenamiento

class Storage:
    """Escribe solo los archivos elegidos. Mientras están incompletos se llaman «nombre.aeropart»."""

    def __init__(self, t: metainfo.Torrent, dest: str, selected: set[int]):
        self.t, self.selected = t, selected
        root = dest if t.single else os.path.join(dest, t.name)
        self.final = {i: os.path.join(root, *f.path.split("/")) if not t.single else os.path.join(dest, f.path)
                      for i, f in enumerate(t.files)}
        self.created: set[str] = set()
        self.done_files: set[int] = set()

    def part(self, i: int) -> str:
        return self.final[i] + PART

    def current(self, i: int) -> str:
        return self.final[i] if i in self.done_files else self.part(i)

    def spans(self, piece: int):
        """(índice de archivo, posición en el archivo, posición en la pieza, longitud) de la pieza."""
        t = self.t
        start = piece * t.piece_length
        end = start + t.piece_size(piece)
        for i, f in enumerate(t.files):
            a, b = max(start, f.offset), min(end, f.offset + f.length)
            if a < b:
                yield i, a - f.offset, a - start, b - a

    def covered(self, piece: int) -> bool:
        """¿Toda la pieza cae en archivos elegidos? (si no, no se puede comprobar desde el disco)."""
        return all(i in self.selected for i, *_ in self.spans(piece))

    def write(self, piece: int, data: bytes) -> None:
        for i, foff, poff, n in self.spans(piece):
            if i not in self.selected:
                continue
            path = self.current(i)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                with open(path, "wb") as fh:
                    fh.truncate(self.t.files[i].length)
                if path.endswith(PART):
                    self.created.add(path)
            with open(path, "r+b") as fh:
                fh.seek(foff)
                fh.write(data[poff:poff + n])

    def read(self, piece: int) -> bytes | None:
        out = bytearray()
        for i, foff, _poff, n in self.spans(piece):
            path = self.final[i] if os.path.exists(self.final[i]) and not os.path.exists(self.part(i)) \
                else self.part(i)
            try:
                with open(path, "rb") as fh:
                    fh.seek(foff)
                    chunk = fh.read(n)
            except OSError:
                return None
            if len(chunk) != n:
                return None
            out += chunk
        return bytes(out)

    def finish_file(self, i: int) -> str:
        """Todas sus piezas comprobadas: «.aeropart» → nombre definitivo (sin pisar nada que ya exista)."""
        src, dst = self.part(i), self.final[i]
        if i in self.done_files:
            return dst
        if os.path.exists(src):
            if os.path.exists(dst):
                stem, ext = os.path.splitext(dst)
                k = 2
                while os.path.exists(f"{stem} ({k}){ext}"):
                    k += 1
                dst = f"{stem} ({k}){ext}"
                self.final[i] = dst
            os.replace(src, dst)
            self.created.discard(src)
        elif self.t.files[i].length == 0:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "ab").close()
        self.done_files.add(i)
        return dst

    def remove_partial(self) -> None:
        for p in list(self.created):
            try:
                os.unlink(p)
            except OSError:
                pass
            self.created.discard(p)


# ----------------------------------------------------------------------------- descarga

@dataclass
class Snapshot:
    state: str
    progress: float
    done: int
    total: int
    rate: float
    peers: int
    known: int
    seeds: int
    eta: float | None
    message: str = ""
    files_done: int = 0


@dataclass
class _Piece:
    size: int
    blocks: dict[int, bytes] = field(default_factory=dict)
    requested: dict[int, float] = field(default_factory=dict)   # bloque → instante de la petición


class _Peer:
    def __init__(self, addr):
        self.addr = addr
        self.reader = self.writer = None
        self.bits: set[int] = set()
        self.choked = True
        self.interested = False
        self.pending: set[tuple[int, int]] = set()
        self.alive = True


class Download:
    """Una descarga. Los métodos públicos se llaman desde la interfaz; el trabajo va en el bucle del motor."""

    def __init__(self, engine: "Engine", t: metainfo.Torrent, dest: str, selected: set[int] | None = None):
        self.engine, self.t, self.dest = engine, t, os.path.abspath(dest)
        self.selected = set(range(len(t.files))) if selected is None else set(selected)
        if not self.selected:
            raise EngineError("Elige al menos un archivo.")
        self.storage = Storage(t, self.dest, self.selected)
        self.need = {p for i in self.selected for p in t.pieces_of(t.files[i])}
        self.have: set[int] = set()
        self.total = sum(t.files[i].length for i in self.selected)
        self.state, self.message = "checking", ""
        self.peers: dict[tuple, _Peer] = {}
        self._bg: set[asyncio.Future] = set()     # tareas sueltas: sin referencia, asyncio podría liberarlas a medias
        self.known: set[tuple] = set()
        self.extra_peers: list[tuple[str, int]] = []      # pares añadidos a mano (o por las pruebas)
        self.inflight: dict[int, _Piece] = {}
        self.uploaded = 0
        self._rate_win: list[tuple[float, int]] = []
        self._task: asyncio.Task | None = None
        self.started = time.time()

    # -- lectura desde la interfaz (sin bloqueos: solo números)
    def done_bytes(self) -> int:
        n = 0
        for p in self.have:
            for i, _fo, _po, ln in self.storage.spans(p):
                if i in self.selected:
                    n += ln
        return n

    def snapshot(self) -> Snapshot:
        now = time.time()
        win = [(t, b) for t, b in self._rate_win if now - t <= 5]
        rate = sum(b for _t, b in win) / 5.0
        done = self.done_bytes()
        left = max(0, self.total - done)
        seeds = sum(1 for p in self.peers.values() if len(p.bits) == len(self.t.pieces))
        return Snapshot(self.state, done / self.total if self.total else 1.0, done, self.total, rate,
                        sum(1 for p in self.peers.values() if p.writer), len(self.known), seeds,
                        left / rate if rate > 1 and left else None, self.message, len(self.storage.done_files))

    # -- control
    def start(self):
        self.engine.call(self._start)

    def pause(self):
        self.engine.call(self._stop, "paused")

    def cancel(self, remove_partial: bool = True):
        self.engine.call(self._cancel, remove_partial)

    # -- dentro del bucle
    async def _start(self):
        if self._task is None or self._task.done():
            self.state, self.message = "checking", ""
            self._task = asyncio.ensure_future(self._run())

    async def _stop(self, state: str):
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._close_all()
        if self.state != "done":
            self.state = state

    async def _cancel(self, remove_partial: bool):
        await self._stop("cancelled")
        if remove_partial:
            await asyncio.to_thread(self.storage.remove_partial)

    def _close_all(self):
        for p in list(self.peers.values()):
            p.alive = False
            if p.writer is not None:
                try:
                    p.writer.close()
                except Exception:  # noqa: BLE001
                    pass
        self.peers.clear()
        self.inflight.clear()

    async def _run(self):
        try:
            await asyncio.to_thread(self._check_existing)
            if not (self.need - self.have):
                await self._complete()
                return
            self.state = "connecting"
            tasks = [asyncio.ensure_future(self._tracker_loop(url)) for url in self.t.trackers]
            tasks.append(asyncio.ensure_future(self._connector()))
            if not self.t.trackers and not self.extra_peers:
                self.message = "Este torrent no tiene trackers: sin DHT no se pueden encontrar pares."
            try:
                while self.need - self.have:
                    await asyncio.sleep(0.5)
                    if self.state == "connecting" and any(p.writer for p in self.peers.values()):
                        self.state = "downloading"
                    self._timeouts()
                await self._complete()
            finally:
                for t in tasks:
                    t.cancel()
                self._close_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - cualquier fallo se muestra en la descarga, no tumba el motor
            self.state, self.message = "error", str(e) or type(e).__name__

    async def _complete(self):
        for i in sorted(self.selected):
            await asyncio.to_thread(self.storage.finish_file, i)
        self.state, self.message = "done", ""
        for url in self.t.trackers:
            self._spawn(asyncio.to_thread(self._safe_announce, url, "completed"))

    def _spawn(self, coro) -> asyncio.Future:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    def _safe_announce(self, url, event):
        try:
            return announce(url, self.t.info_hash, max(0, self.total - self.done_bytes()), self.done_bytes(),
                            self.uploaded, event)
        except Exception:  # noqa: BLE001
            return [], 1800

    def _check_existing(self):
        """Reanudar: comprueba con SHA-1 lo que ya está en el disco (solo piezas enteramente propias)."""
        for i in self.selected:     # los «.aeropart» de una sesión anterior también son de AERO: cancelar los quita
            if os.path.exists(self.storage.part(i)):
                self.storage.created.add(self.storage.part(i))
        for p in sorted(self.need):
            if not self.storage.covered(p):
                continue
            data = self.storage.read(p)
            if data is not None and hashlib.sha1(data).digest() == self.t.pieces[p]:
                self.have.add(p)
        for i in self.selected:
            if all(p in self.have for p in self.t.pieces_of(self.t.files[i])) and \
                    os.path.exists(self.storage.final[i]) and not os.path.exists(self.storage.part(i)):
                self.storage.done_files.add(i)

    async def _tracker_loop(self, url: str):
        event = "started"
        while True:
            left = max(0, self.total - self.done_bytes())
            try:
                peers, interval = await asyncio.to_thread(announce, url, self.t.info_hash, left, self.done_bytes(),
                                                          self.uploaded, event)
                self.known.update(peers)
                event = ""
                if not peers and not self.known:
                    self.message = "El tracker no conoce pares para este torrent ahora mismo."
                elif self.message.startswith(("El tracker", "No se pudo")):
                    self.message = ""
            except Exception as e:  # noqa: BLE001
                interval = 120
                if not self.known:
                    self.message = f"No se pudo contactar con el tracker: {e}"
            await asyncio.sleep(max(60, min(interval, 1800)))

    async def _connector(self):
        tried: dict[tuple, float] = {}
        while True:
            self.known.update(self.extra_peers)
            now = time.time()
            for addr in list(self.known):
                if len(self.peers) >= MAX_PEERS:
                    break
                if addr in self.peers or now - tried.get(addr, 0) < 60:
                    continue
                tried[addr] = now
                peer = _Peer(addr)
                self.peers[addr] = peer
                self._spawn(self._peer_loop(peer))
            await asyncio.sleep(2)

    def _timeouts(self):
        now = time.time()
        for piece in self.inflight.values():
            for b, t0 in list(piece.requested.items()):
                if now - t0 > 30:
                    del piece.requested[b]

    # -- protocolo de pares
    async def _send(self, peer: _Peer, msg_id: int | None, payload: bytes = b""):
        if peer.writer is None:
            return
        if msg_id is None:
            peer.writer.write(struct.pack(">I", 0))
        else:
            peer.writer.write(struct.pack(">IB", 1 + len(payload), msg_id) + payload)
        await peer.writer.drain()

    async def _peer_loop(self, peer: _Peer):
        try:
            peer.reader, peer.writer = await asyncio.wait_for(asyncio.open_connection(*peer.addr), 8)
            peer.writer.write(b"\x13BitTorrent protocol" + b"\x00" * 8 + self.t.info_hash + PEER_ID)
            await peer.writer.drain()
            hs = await asyncio.wait_for(peer.reader.readexactly(68), 15)
            if hs[28:48] != self.t.info_hash:
                raise EngineError("El par sirve otro torrent.")
            if self.have:
                bits = bytearray((len(self.t.pieces) + 7) // 8)
                for p in self.have:
                    bits[p // 8] |= 0x80 >> (p % 8)
                await self._send(peer, 5, bytes(bits))
            await self._send(peer, 2)
            peer.interested = True
            while peer.alive and self.need - self.have:
                head = await asyncio.wait_for(peer.reader.readexactly(4), 120)
                n = struct.unpack(">I", head)[0]
                if n == 0:
                    continue
                if n > BLOCK + 64 and n > len(self.t.pieces) // 8 + 64:
                    raise EngineError("Mensaje demasiado grande.")
                body = await asyncio.wait_for(peer.reader.readexactly(n), 60)
                await self._on_message(peer, body[0], body[1:])
                await self._fill(peer)
        except (asyncio.TimeoutError, ConnectionError, OSError, EngineError, asyncio.IncompleteReadError):
            pass
        finally:
            peer.alive = False
            for piece_i, off in peer.pending:
                piece = self.inflight.get(piece_i)
                if piece is not None:
                    piece.requested.pop(off, None)
            if peer.writer is not None:
                try:
                    peer.writer.close()
                except Exception:  # noqa: BLE001
                    pass
            self.peers.pop(peer.addr, None)

    async def _on_message(self, peer: _Peer, mid: int, data: bytes):
        if mid == 0:
            peer.choked = True
            for piece_i, off in peer.pending:
                p = self.inflight.get(piece_i)
                if p is not None:
                    p.requested.pop(off, None)
            peer.pending.clear()
        elif mid == 1:
            peer.choked = False
        elif mid == 4 and len(data) >= 4:
            peer.bits.add(struct.unpack(">I", data[:4])[0])
        elif mid == 5:
            for i, byte in enumerate(data):
                for b in range(8):
                    if byte & (0x80 >> b) and i * 8 + b < len(self.t.pieces):
                        peer.bits.add(i * 8 + b)
        elif mid == 6 and len(data) >= 12:
            await self._serve(peer, *struct.unpack(">III", data[:12]))
        elif mid == 7 and len(data) >= 8:
            idx, off = struct.unpack(">II", data[:8])
            await self._on_block(peer, idx, off, data[8:])

    async def _serve(self, peer: _Peer, idx: int, off: int, length: int):
        """Cortesía: entregar bloques de piezas que ya tenemos a los pares conectados."""
        if idx not in self.have or length > BLOCK or idx >= len(self.t.pieces):
            return
        data = await asyncio.to_thread(self.storage.read, idx)
        if data is None:
            return
        await self._send(peer, 7, struct.pack(">II", idx, off) + data[off:off + length])
        self.uploaded += length

    def _pick(self, peer: _Peer) -> int | None:
        wanted = [p for p in peer.bits if p in self.need and p not in self.have]
        if not wanted:
            return None
        for p in wanted:            # primero, terminar piezas empezadas
            piece = self.inflight.get(p)
            if piece is not None and self._free_block(piece) is not None:
                return p
        fresh = [p for p in wanted if p not in self.inflight]
        if not fresh:
            # modo final: se piden otra vez bloques ya pedidos a otros pares
            return random.choice(wanted) if len(self.need - self.have) <= 8 else None
        counts = {p: sum(1 for q in self.peers.values() if p in q.bits) for p in fresh[:400]}
        rarest = min(counts.values())
        return random.choice([p for p, c in counts.items() if c == rarest])

    @staticmethod
    def _free_block(piece: _Piece) -> int | None:
        for off in range(0, piece.size, BLOCK):
            if off not in piece.blocks and off not in piece.requested:
                return off
        return None

    async def _fill(self, peer: _Peer):
        if peer.choked or not peer.alive:
            return
        while len(peer.pending) < PIPELINE:
            p = self._pick(peer)
            if p is None:
                return
            piece = self.inflight.setdefault(p, _Piece(self.t.piece_size(p)))
            off = self._free_block(piece)
            if off is None:     # modo final: cualquier bloque que falte
                missing = [o for o in range(0, piece.size, BLOCK) if o not in piece.blocks]
                if not missing or (p, missing[0]) in peer.pending:
                    return
                off = missing[0]
            piece.requested[off] = time.time()
            peer.pending.add((p, off))
            await self._send(peer, 6, struct.pack(">III", p, off, min(BLOCK, piece.size - off)))

    async def _on_block(self, peer: _Peer, idx: int, off: int, data: bytes):
        peer.pending.discard((idx, off))
        piece = self.inflight.get(idx)
        if piece is None or idx in self.have:
            return
        piece.blocks[off] = data
        piece.requested.pop(off, None)
        self._rate_win.append((time.time(), len(data)))
        if len(self._rate_win) > 4000:
            self._rate_win = self._rate_win[-2000:]
        if sum(len(b) for b in piece.blocks.values()) < piece.size:
            return
        blob = b"".join(piece.blocks[o] for o in sorted(piece.blocks))[:piece.size]
        del self.inflight[idx]
        if hashlib.sha1(blob).digest() != self.t.pieces[idx]:
            return     # pieza dañada: se descarta y se volverá a pedir
        await asyncio.to_thread(self.storage.write, idx, blob)
        self.have.add(idx)
        if self.state == "connecting":
            self.state = "downloading"
        for i in self.selected:
            if i not in self.storage.done_files and all(p in self.have for p in self.t.pieces_of(self.t.files[i])):
                await asyncio.to_thread(self.storage.finish_file, i)
        for q in list(self.peers.values()):
            if q.writer is not None and q.alive:
                try:
                    await self._send(q, 4, struct.pack(">I", idx))
                except (ConnectionError, OSError):
                    pass


class Engine:
    """Bucle asyncio en un hilo propio. `call(coro_fn, *args)` lo ejecuta allí desde cualquier hilo."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="aero-torrent", daemon=True)
        self.thread.start()
        self.downloads: list[Download] = []

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, fn, *args):
        return asyncio.run_coroutine_threadsafe(fn(*args), self.loop)

    def add(self, t: metainfo.Torrent, dest: str, selected: set[int] | None = None, start: bool = True) -> Download:
        d = Download(self, t, dest, selected)
        self.downloads.append(d)
        if start:
            d.start()
        return d

    def stop(self, timeout: float = 5.0):
        """Para todas las descargas (sin borrar nada) y el bucle."""
        futs = [self.call(d._stop, "paused") for d in self.downloads if d.state not in ("done", "cancelled")]
        for f in futs:
            try:
                f.result(timeout)
            except Exception:  # noqa: BLE001
                pass
        _close_loop(self.loop, self.thread, timeout)


async def _cancel_all():
    me = asyncio.current_task()
    tasks = [t for t in asyncio.all_tasks() if t is not me]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _close_loop(loop, thread, timeout: float):
    """Cancela todo lo pendiente, para el bucle y espera al hilo (sin «Task was destroyed but it is pending»)."""
    try:
        asyncio.run_coroutine_threadsafe(_cancel_all(), loop).result(timeout)
    except Exception:  # noqa: BLE001
        pass
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout)
    if not thread.is_alive():
        loop.close()


# ----------------------------------------------------------------------------- semilla (pruebas y uso local)

class Seeder:
    """Sirve un torrent completo a quien se conecte (escucha solo en la dirección indicada, p. ej. 127.0.0.1).
    AERO Player no lo usa para descargar; existe para comprobar el motor de punta a punta sin Internet."""

    def __init__(self, t: metainfo.Torrent, folder: str, host: str = "127.0.0.1", port: int = 0):
        self.t, self.host, self.port = t, host, port
        self.storage = Storage(t, folder, set(range(len(t.files))))
        self.storage.done_files = set(range(len(t.files)))
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.server = server = self.loop.run_until_complete(asyncio.start_server(self._client, self.host, self.port))
        self.port = server.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()

    async def _client(self, reader, writer):
        try:
            hs = await reader.readexactly(68)
            if hs[28:48] != self.t.info_hash:
                return
            writer.write(b"\x13BitTorrent protocol" + b"\x00" * 8 + self.t.info_hash + b"-AE0000-seedseedseed")
            n = len(self.t.pieces)
            bits = bytearray((n + 7) // 8)
            for p in range(n):
                bits[p // 8] |= 0x80 >> (p % 8)
            writer.write(struct.pack(">IB", 1 + len(bits), 5) + bytes(bits))
            writer.write(struct.pack(">IB", 1, 1))   # unchoke
            await writer.drain()
            while True:
                n = struct.unpack(">I", await reader.readexactly(4))[0]
                if n == 0:
                    continue
                body = await reader.readexactly(n)
                if body[0] == 6:
                    idx, off, ln = struct.unpack(">III", body[1:13])
                    data = self.storage.read(idx)
                    block = data[off:off + ln]
                    writer.write(struct.pack(">IBII", 9 + len(block), 7, idx, off) + block)
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            writer.close()

    def stop(self):
        self.loop.call_soon_threadsafe(self.server.close)
        _close_loop(self.loop, self.thread, 5.0)
