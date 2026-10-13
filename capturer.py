"""
Motor de captura de comentarios de TikTok LIVE.

Diseño (aprendido a golpes, ver skill tiktok-live-capture):
  * `client.start()` NO bloquea: devuelve el Task del heartbeat del WebSocket.
  * Parar el WS ANTES de cerrar ficheros, o el siguiente evento revienta con
    "I/O operation on closed file".
  * `asyncio.CancelledError` hereda de BaseException, no de Exception.
  * Deduplicar por `common.msg_id`, NUNCA por (usuario, texto).
  * Escritura incremental con flush: si el proceso muere, no se pierde la sesión.
"""

from __future__ import annotations

import asyncio
import csv
import queue
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Windows: el SelectorEventLoop es obligatorio para el WS de TikTok.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sesiones"

# ---------------------------------------------------------------------------
# Definición de columnas: (clave interna, encabezado del Excel)
# ---------------------------------------------------------------------------
COMMENT_COLUMNS: list[tuple[str, str]] = [
    ("n", "Nº"),
    ("fecha", "Fecha"),
    ("hora", "Hora (HH:MM:SS)"),
    ("hora_ms", "Hora exacta (con ms)"),
    ("timestamp_iso", "Fecha-hora ISO 8601"),
    ("unix_ms", "Timestamp Unix (ms)"),
    ("latencia_ms", "Latencia recepción (ms)"),
    ("usuario", "Usuario (@)"),
    ("nickname", "Nombre visible"),
    ("user_id", "ID del autor"),
    ("sec_uid", "Sec UID"),
    ("comentario", "Comentario"),
    ("idioma", "Idioma"),
    ("msg_id", "ID del mensaje"),
    ("es_moderador", "Moderador"),
    ("es_suscriptor", "Suscriptor"),
    ("es_seguidor", "Seguidor"),
    ("es_mutuo", "Seguimiento mutuo"),
    ("es_amigo", "Amigo"),
    ("es_top_gifter", "Top gifter"),
    ("nivel_miembro", "Nivel de miembro"),
    ("nivel_gifter", "Nivel de gifter"),
    ("insignias", "Insignias"),
    ("menciones", "Menciones"),
    ("perfil", "Perfil"),
    ("room_id", "Sala (room_id)"),
]

GIFT_COLUMNS: list[tuple[str, str]] = [
    ("n", "Nº"),
    ("fecha", "Fecha"),
    ("hora_ms", "Hora exacta (con ms)"),
    ("usuario", "Usuario (@)"),
    ("nickname", "Nombre visible"),
    ("user_id", "ID del autor"),
    ("regalo", "Regalo"),
    ("gift_id", "ID del regalo"),
    ("diamantes", "Diamantes unitarios"),
    ("repeticiones", "Repeticiones"),
    ("combo", "Combo"),
    ("diamantes_totales", "Diamantes totales"),
    ("msg_id", "ID del mensaje"),
    ("room_id", "Sala (room_id)"),
]

# El CSV usa exactamente los mismos encabezados legibles que el Excel.
HEADER_BY_KEY: dict[str, str] = dict(COMMENT_COLUMNS)
CSV_FIELDNAMES: list[str] = [header for _, header in COMMENT_COLUMNS]


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
class CaptureError(Exception):
    """Error ya traducido a lenguaje claro; no se vuelve a procesar."""
# ---------------------------------------------------------------------------
# Utilidades defensivas
# ---------------------------------------------------------------------------
# Escenas de insignia (BadgeSceneType) traducidas a algo legible.
BADGE_LABELS = {
    "ADMIN": "Moderador",
    "FRIENDS": "Amigo",
    "SUBSCRIBER": "Suscriptor",
    "NEW_SUBSCRIBER": "Suscriptor nuevo",
    "FANS": "Fan",
    "USER_GRADE": "Nivel de usuario",
    "RANK_LIST": "Top gifter",
    "LIVE_PRO": "Live Pro",
    "ANCHOR": "Anfitrión",
    "ENIGMA": "Enigma",
    "FIRST_RECHARGE": "Primera recarga",
    "CLASS_RANK": "Ranking de clase",
    "ACTIVITY": "Actividad",
    "STATE_CONTROLLED_MEDIA": "Medio controlado",
}


def dig(obj: Any, *path: str, default: Any = None) -> Any:
    """getattr encadenado a prueba de nulos: dig(user, 'follow_info', 'follower_count')."""
    cur = obj
    for key in path:
        if cur is None:
            return default
        cur = getattr(cur, key, None)
    return default if cur is None else cur


def _truthy(value: Any) -> bool:
    """betterproto devuelve 0/'' para campos no fijados."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "none")
    try:
        return bool(value)
    except Exception:
        return False


def _parse_server_time(common: Any) -> Optional[datetime]:
    """Hora real de publicación según el servidor de TikTok (create_time).

    El proto lo manda como entero; según el despliegue viene en segundos o en
    milisegundos, así que se desambigua por magnitud.
    """
    raw = getattr(common, "create_time", None)
    if raw in (None, "", 0, "0"):
        return None
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # < 1e11 => segundos (1e11 s ≈ año 5138); si no, milisegundos.
    if value < 100_000_000_000:
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return dt.astimezone()


def _badge_entries(user: Any) -> list[tuple[str, str]]:
    """Devuelve [(escena, nivel)] leyendo `badge_list` del proto directamente.

    OJO: `ExtendedUser.get_all_badges` (y con él `member_level`, `gifter_level`,
    `is_moderator`, `is_friend`, `is_top_gifter`) está ROTO contra el proto
    instalado: busca `badge.badge_scene` y `badge.log_extra`, campos que no
    existen en TikTokLiveProto 0.2.2 (los reales son `scene_type` y
    `privilege_log_extra`). Por eso siempre devuelve vacío. Se lee a mano.
    """
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for badge in getattr(user, "badge_list", None) or []:
        scene = str(getattr(badge, "scene_type", "") or "")
        scene = scene.replace("BADGE_SCENE_TYPE_", "").strip()
        if not scene or scene == "UNKNOWN":
            continue
        level = dig(badge, "privilege_log_extra", "level")
        level = "" if level in (None, 0, "0") else str(level)
        if (scene, level) in seen:
            continue
        seen.add((scene, level))
        entries.append((scene, level))

    # Vía alternativa por si una versión futura arregla el helper de la librería.
    if not entries:
        try:
            raw = getattr(user, "get_all_badges", None)
            raw = raw() if callable(raw) else raw
            for item in raw or []:
                if isinstance(item, (tuple, list)) and len(item) == 2:
                    name, level = str(item[0]), str(item[1] or "")
                    if name and name != "UNKNOWN":
                        entries.append((name.replace("BADGE_SCENE_TYPE_", ""), level))
        except Exception:
            pass

    return entries


def _badges(user: Any, entries: Optional[list[tuple[str, str]]] = None) -> str:
    """Insignias legibles, p. ej. «Fan 12, Nivel de usuario 8»."""
    parts = []
    for scene, level in entries if entries is not None else _badge_entries(user):
        label = BADGE_LABELS.get(scene, scene)
        parts.append(f"{label} {level}".strip())
    return ", ".join(parts)


def _mentions(event: Any) -> str:
    found: list[str] = []
    at_user = getattr(event, "at_user", None)
    if at_user is not None and (dig(at_user, "display_id") or dig(at_user, "id")):
        handle = dig(at_user, "display_id") or dig(at_user, "id")
        found.append("@" + str(handle))
    for mention in getattr(event, "mention_users", None) or []:
        handle = dig(mention, "display_id")
        if handle:
            found.append("@" + str(handle))
    return ", ".join(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Sesión de captura
# ---------------------------------------------------------------------------
class CaptureSession:
    """Una sesión de captura: un usuario de TikTok, un CSV, un Excel."""

    def __init__(self, unique_id: str, capture_gifts: bool = False) -> None:
        self.unique_id = unique_id.strip().lstrip("@")
        self.capture_gifts = capture_gifts

        self.rows: list[dict] = []
        self.gift_rows: list[dict] = []

        self.state = "idle"          # idle|connecting|live|stopping|stopped|error|offline
        self.message = "Sin iniciar"
        self.error: Optional[str] = None

        self.room_id: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None
        self.connected_at: Optional[datetime] = None

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_path = SESSIONS_DIR / f"comentarios_{self.unique_id}_{self.session_id}.csv"
        self.xlsx_path: Optional[Path] = None

        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        self._stop_requested = threading.Event()
        self._stop_evt: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._heartbeat = None
        self._thread: Optional[threading.Thread] = None
        self._csv_fp = None
        self._csv_writer: Optional[csv.DictWriter] = None
        self._closed = False

    # -- publicación hacia la interfaz web ---------------------------------
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    def _publish(self, payload: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except queue.Full:
                self.unsubscribe(q)

    # -- estado ------------------------------------------------------------
    @property
    def elapsed_s(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.stopped_at or datetime.now()
        return (end - self.started_at).total_seconds()

    def stats(self) -> dict:
        users = {r.get("user_id") for r in self.rows if r.get("user_id")}
        minutes = max(self.elapsed_s / 60.0, 1 / 60.0)
        return {
            "comments": len(self.rows),
            "unique_users": len(users),
            "gifts": len(self.gift_rows),
            "elapsed_s": round(self.elapsed_s, 1),
            "per_minute": round(len(self.rows) / minutes, 1),
        }

    def status(self) -> dict:
        return {
            "state": self.state,
            "message": self.message,
            "error": self.error,
            "unique_id": self.unique_id,
            "room_id": self.room_id,
            "session_id": self.session_id,
            "capture_gifts": self.capture_gifts,
            "started_at": self.started_at.isoformat(timespec="seconds") if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat(timespec="seconds") if self.stopped_at else None,
            "csv": str(self.csv_path) if self.csv_path.exists() else None,
            "xlsx": str(self.xlsx_path) if self.xlsx_path else None,
            "stats": self.stats(),
        }

    def snapshot(self) -> dict:
        """Todo lo que necesita un navegador que se acaba de conectar."""
        return {
            "status": self.status(),
            "columns": [{"key": k, "header": h} for k, h in COMMENT_COLUMNS],
            "rows": list(self.rows),
        }

    # -- arranque / parada -------------------------------------------------
    def start(self) -> bool:
        if self.state in ("connecting", "live", "stopping"):
            return False
        self.state = "connecting"
        self.error = None
        self.message = f"Conectando con @{self.unique_id}…"
        self.started_at = datetime.now()
        self.stopped_at = None
        self._open_csv()
        self._thread = threading.Thread(target=self._thread_main, name="captura-tiktok", daemon=True)
        self._thread.start()
        self._publish({"type": "status", "status": self.status()})
        return True

    def stop(self) -> bool:
        if self.state not in ("connecting", "live"):
            return False
        self.state = "stopping"
        self.message = "Deteniendo captura…"
        self._stop_requested.set()
        if self._loop is not None and self._stop_evt is not None:
            try:
                self._loop.call_soon_threadsafe(self._stop_evt.set)
            except RuntimeError:
                pass
        self._publish({"type": "status", "status": self.status()})
        return True

    def wait(self, timeout: float = 15.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # -- ficheros ----------------------------------------------------------
    def _open_csv(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        # utf-8-sig: si el usuario abre el CSV directamente en Excel, sale bien.
        self._csv_fp = open(self.csv_path, "w", encoding="utf-8-sig", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_fp,
            fieldnames=CSV_FIELDNAMES,  # encabezados legibles, iguales que en el Excel
        )
        self._csv_writer.writeheader()
        self._csv_fp.flush()

    def _write_csv(self, row: dict) -> None:
        if self._closed or self._csv_writer is None:
            return
        try:
            self._csv_writer.writerow(
                {HEADER_BY_KEY[key]: row.get(key, "") for key, _ in COMMENT_COLUMNS}
            )
            self._csv_fp.flush()
        except (ValueError, OSError):
            # Fichero cerrado por una carrera al parar: se ignora en silencio.
            pass

    def _close_files(self) -> None:
        self._closed = True
        if self._csv_fp is not None:
            try:
                self._csv_fp.flush()
                self._csv_fp.close()
            except (ValueError, OSError):
                pass
            self._csv_fp = None

    # -- hilo con el event loop -------------------------------------------
    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._run())
        except (Exception, asyncio.CancelledError) as exc:
            self.error = self._friendly_error(exc)
            self.state = "error"
            self.message = self.error
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except (Exception, asyncio.CancelledError):
                pass
            try:
                loop.close()
            except (Exception, asyncio.CancelledError):
                pass

            self._close_files()
            self.stopped_at = self.stopped_at or datetime.now()
            if self.state != "error":
                self.state = "stopped"
                self.message = "Captura detenida"
            self._loop = None
            self._heartbeat = None

            # Excel automático al cerrar: el usuario nunca se queda sin datos.
            if self.rows:
                try:
                    from exporter import export_session
                    self.xlsx_path = export_session(self)
                except Exception as exc:  # el Excel no debe tumbar la sesión
                    self.error = self.error or f"No se pudo generar el Excel: {exc}"
            else:
                # Sesión sin datos (p. ej. cuenta no estaba en directo): no dejar basura.
                try:
                    self.csv_path.unlink(missing_ok=True)
                except OSError:
                    pass

            self._publish({"type": "status", "status": self.status()})

    async def _run(self) -> None:
        from TikTokLive import TikTokLiveClient
        from TikTokLive.events import CommentEvent, ConnectEvent, DisconnectEvent, GiftEvent

        self._stop_evt = asyncio.Event()
        if self._stop_requested.is_set():
            self._stop_evt.set()

        client = TikTokLiveClient(unique_id=f"@{self.unique_id}")
        self.client = client

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent) -> None:
            self.room_id = str(
                getattr(event, "room_id", None) or getattr(client, "room_id", None) or ""
            ) or None
            self.connected_at = datetime.now()
            self.state = "live"
            self.message = f"En directo · sala {self.room_id}"
            self._publish({"type": "status", "status": self.status()})

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent) -> None:
            self._handle_comment(event)

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent) -> None:
            if self.state == "live":
                self.state = "offline"
                self.message = "El directo terminó o se perdió la conexión"
                self._publish({"type": "status", "status": self.status()})

        if self.capture_gifts:

            @client.on(GiftEvent)
            async def on_gift(event: GiftEvent) -> None:
                self._handle_gift(event)

        # Pre-chequeo barato: is_live() no usa el servidor de firma.
        try:
            is_live = await client.is_live()
            if is_live is False:
                raise CaptureError(f"@{self.unique_id} no está en directo ahora mismo.")
        except CaptureError:
            raise
        except (Exception, asyncio.CancelledError) as exc:
            if self._is_rate_limited(exc):
                raise CaptureError(
                    "El servidor de firma (Euler Stream) está limitando las peticiones. "
                    "Espera 2-5 minutos y reintenta."
                ) from exc
            # Cualquier otro fallo del pre-chequeo no impide intentar conectar.

        try:
            heartbeat = await client.start()  # <- devuelve un Task, NO bloquea
        except (Exception, asyncio.CancelledError) as exc:
            raise CaptureError(self._friendly_error(exc)) from exc

        self._heartbeat = heartbeat
        wait_task = asyncio.create_task(self._stop_evt.wait())
        try:
            await asyncio.wait([heartbeat, wait_task], return_when=asyncio.FIRST_COMPLETED)
        except (Exception, asyncio.CancelledError):
            pass

        # ORDEN CRÍTICO: cancelar el WS y esperarlo antes de cerrar ficheros.
        for task in (heartbeat, wait_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (heartbeat, wait_task) if t is not None), return_exceptions=True
        )
        try:
            await asyncio.wait_for(client.disconnect(), timeout=5)
        except (Exception, asyncio.CancelledError):
            pass

    # -- handlers ----------------------------------------------------------
    def ingest_event(self, event: Any) -> None:
        """Inyecta un evento ya construido (modo demo y pruebas).

        Pasa por los mismos handlers que un evento real, así que valida de
        verdad la lectura de campos y la escritura a CSV/XLSX.
        """
        name = type(event).__name__
        if name == "CommentEvent":
            self._handle_comment(event)
        elif name == "GiftEvent":
            self._handle_gift(event)

    def _handle_comment(self, event: Any) -> None:
        if self._closed:
            return

        common = getattr(event, "common", None)
        msg_id = str(getattr(common, "msg_id", "") or "")

        # Deduplicación por msg_id real (nunca por texto: hay repeticiones legítimas).
        if msg_id:
            with self._lock:
                if msg_id in self._seen:
                    return
                self._seen.add(msg_id)

        received = datetime.now().astimezone()
        published = _parse_server_time(common)
        stamp = published or received
        latency = None
        if published is not None:
            delta = int((received - published).total_seconds() * 1000)
            if 0 <= delta <= 600_000:  # descarta relojes desincronizados
                latency = delta

        user = getattr(event, "user", None)
        identity = getattr(event, "user_identity", None)

        handle = dig(user, "display_id") or dig(user, "unique_id") or "desconocido"
        user_id = dig(user, "id")

        # Las insignias son la fuente fiable; `user_identity` las refuerza.
        entries = _badge_entries(user)          # se lee el proto una sola vez
        scenes = {scene for scene, _ in entries}
        levels = {scene: level for scene, level in entries}
        is_moderator = _truthy(dig(identity, "is_moderator_of_anchor")) or "ADMIN" in scenes
        is_subscriber = (
            _truthy(getattr(event, "user_is_super_fan", None))
            or _truthy(dig(identity, "is_subscriber_of_anchor"))
            or _truthy(dig(user, "is_subscribe"))
            or bool({"SUBSCRIBER", "NEW_SUBSCRIBER"} & scenes)
        )
        is_follower = _truthy(dig(identity, "is_follower_of_anchor")) or _truthy(
            dig(user, "is_follower")
        )
        is_mutual = _truthy(dig(identity, "is_mutual_following_with_anchor"))
        is_friend = _truthy(dig(user, "is_friend")) or "FRIENDS" in scenes
        is_top_gifter = _truthy(dig(user, "is_top_gifter")) or "RANK_LIST" in scenes

        # Niveles: insignia primero, campo directo como respaldo.
        member_level = levels.get("FANS") or dig(user, "member_level", default="")
        gifter_level = levels.get("USER_GRADE") or dig(user, "gifter_level", default="")

        row = {
            "n": 0,  # se rellena bajo lock
            "fecha": stamp.strftime("%Y-%m-%d"),
            "hora": stamp.strftime("%H:%M:%S"),
            "hora_ms": stamp.strftime("%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}",
            "timestamp_iso": stamp.isoformat(timespec="milliseconds"),
            "unix_ms": int(stamp.timestamp() * 1000),
            "latencia_ms": latency,
            "usuario": f"@{handle}",
            "nickname": str(dig(user, "nickname") or dig(user, "nick_name") or ""),
            "user_id": user_id,
            "sec_uid": str(dig(user, "sec_uid") or ""),
            "comentario": str(getattr(event, "content", "") or ""),
            "idioma": str(getattr(event, "content_language", "") or ""),
            "msg_id": msg_id,
            "es_moderador": "Sí" if is_moderator else "",
            "es_suscriptor": "Sí" if is_subscriber else "",
            "es_seguidor": "Sí" if is_follower else "",
            "es_mutuo": "Sí" if is_mutual else "",
            "es_amigo": "Sí" if is_friend else "",
            "es_top_gifter": "Sí" if is_top_gifter else "",
            "nivel_miembro": member_level,
            "nivel_gifter": gifter_level,
            "insignias": _badges(user, entries),
            "menciones": _mentions(event),
            "perfil": f"https://www.tiktok.com/@{handle}",
            "room_id": str(getattr(common, "room_id", "") or self.room_id or ""),
        }

        with self._lock:
            row["n"] = len(self.rows) + 1
            self.rows.append(row)

        self._write_csv(row)
        self._publish({"type": "comment", "row": row})

    def _handle_gift(self, event: Any) -> None:
        if self._closed:
            return
        common = getattr(event, "common", None)
        msg_id = str(getattr(common, "msg_id", "") or "")
        if msg_id:
            with self._lock:
                if msg_id in self._seen:
                    return
                self._seen.add(msg_id)

        received = datetime.now().astimezone()
        stamp = _parse_server_time(common) or received
        user = getattr(event, "user", None)
        gift = getattr(event, "gift", None)
        repeats = int(getattr(event, "repeat_count", 0) or 0)
        unit = int(dig(gift, "diamond_count", default=0) or 0)
        handle = dig(user, "display_id") or "desconocido"

        row = {
            "n": 0,
            "fecha": stamp.strftime("%Y-%m-%d"),
            "hora_ms": stamp.strftime("%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}",
            "usuario": f"@{handle}",
            "nickname": str(dig(user, "nickname") or ""),
            "user_id": dig(user, "id"),
            "regalo": str(dig(gift, "name") or dig(gift, "describe") or ""),
            "gift_id": dig(gift, "id", default=""),
            "diamantes": unit,
            "repeticiones": repeats or 1,
            "combo": int(getattr(event, "combo_count", 0) or 0),
            "diamantes_totales": unit * max(repeats, 1),
            "msg_id": msg_id,
            "room_id": str(getattr(common, "room_id", "") or self.room_id or ""),
        }
        with self._lock:
            row["n"] = len(self.gift_rows) + 1
            self.gift_rows.append(row)
        self._publish({"type": "gift", "row": row})

    # -- clasificación de errores -----------------------------------------
    @staticmethod
    def _is_rate_limited(exc: BaseException) -> bool:
        text = f"{type(exc).__name__} {exc}".lower()
        return any(
            token in text
            for token in ("jsondecode", "ratelimit", "rate limit", "429", "too many", "quota")
        )

    def _friendly_error(self, exc: BaseException) -> str:
        if isinstance(exc, CaptureError):
            return str(exc)  # ya viene traducido

        name = type(exc).__name__
        text = f"{name} {exc}".lower()

        if self._is_rate_limited(exc):
            return (
                "Rate limit del servidor de firma (Euler Stream). NO es un fallo de "
                "conexión ni una cuenta inexistente: espera 2-5 minutos y reintenta, "
                "o configura una API key de Euler Stream."
            )
        if "no está en directo" in text or "offline" in text or "not live" in text or "not currently" in text:
            return f"@{self.unique_id} no está en directo ahora mismo."
        if "usernotfound" in text or "user not found" in text or "not found" in text:
            return (
                f"No se encontró la cuenta @{self.unique_id}. Revisa el nombre; si "
                "estás seguro de que existe, suele ser rate limit de firma."
            )
        if "timeout" in text or "timed out" in text:
            return "Se agotó el tiempo de conexión con TikTok. Reintenta en unos segundos."
        if "connection" in text or "websocket" in text:
            return f"No se pudo abrir el WebSocket de TikTok ({name}). Reintenta."
        return f"{name}: {exc}"
