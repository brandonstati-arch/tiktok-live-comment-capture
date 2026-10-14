"""
Servidor de la aplicación de captura de comentarios de TikTok LIVE.

Arranca una interfaz web local que:
  * lanza y detiene la captura en tiempo real,
  * muestra los comentarios según llegan (Server-Sent Events),
  * exporta todo a Excel con columnas organizadas.

Uso:  python app.py [--port 5000] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from capturer import SESSIONS_DIR, CaptureSession
from exporter import export_session

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Registro de sesiones (en memoria)
# ---------------------------------------------------------------------------
SESSIONS: dict[str, CaptureSession] = {}
CURRENT: CaptureSession | None = None
_REGISTRY_LOCK = threading.Lock()


def get_session() -> CaptureSession:
    """Sesión activa; si no hay ninguna, devuelve una inactiva por defecto."""
    global CURRENT
    with _REGISTRY_LOCK:
        if CURRENT is None:
            CURRENT = CaptureSession("sin-sesion")
            CURRENT.state = "idle"
            CURRENT.message = "Introduce un usuario de TikTok y pulsa Iniciar"
            CURRENT._closed = True  # no escribe ficheros
            SESSIONS[CURRENT.session_id] = CURRENT
        return CURRENT


def _safe_path(name: str) -> Path | None:
    """Evita salir del directorio de sesiones al servir ficheros."""
    candidate = (SESSIONS_DIR / name).resolve()
    try:
        candidate.relative_to(SESSIONS_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/stream")
def stream():
    """Flujo SSE: snapshot inicial y luego cada comentario en vivo."""

    def generate():
        current: CaptureSession | None = None
        channel: queue.Queue | None = None
        try:
            while True:
                session = get_session()
                if session is not current:
                    if channel is not None and current is not None:
                        current.unsubscribe(channel)
                    current = session
                    channel = session.subscribe()
                    yield _sse({"type": "snapshot", "data": session.snapshot()})

                try:
                    payload = channel.get(timeout=10)
                except queue.Empty:
                    yield ": keep-alive\n\n"  # mantiene viva la conexión
                    continue
                yield _sse(payload)
        except GeneratorExit:
            return
        finally:
            if channel is not None and current is not None:
                current.unsubscribe(channel)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/status")
def api_status():
    return jsonify(get_session().status())


@app.post("/api/start")
def api_start():
    global CURRENT
    data = request.get_json(silent=True) or {}
    unique_id = (data.get("usuario") or "").strip().lstrip("@")
    if not unique_id:
        return jsonify({"ok": False, "error": "Indica el usuario de TikTok (ej. @usuario)."}), 400

    capture_gifts = bool(data.get("regalos"))

    with _REGISTRY_LOCK:
        active = CURRENT
        if active is not None and active.state in ("connecting", "live", "stopping"):
            return jsonify({"ok": False, "error": "Ya hay una captura en curso. Deténla primero."}), 409
        session = CaptureSession(unique_id, capture_gifts=capture_gifts)
        SESSIONS[session.session_id] = session
        CURRENT = session
        # Poda: conserva las 20 sesiones más recientes en memoria.
        while len(SESSIONS) > 20:
            oldest = next(iter(SESSIONS))
            if SESSIONS[oldest] is not CURRENT:
                SESSIONS.pop(oldest, None)
            else:
                break

    session.start()
    return jsonify({"ok": True, "status": session.status()})


@app.post("/api/stop")
def api_stop():
    session = get_session()
    stopped = session.stop()
    return jsonify({"ok": stopped, "status": session.status()})


@app.post("/api/export")
def api_export():
    session = get_session()
    if not session.rows:
        return jsonify({"ok": False, "error": "Todavía no hay comentarios que exportar."}), 400
    try:
        path = export_session(session)
    except Exception as exc:  # noqa: BLE001 - se informa al usuario
        return jsonify({"ok": False, "error": f"No se pudo generar el Excel: {exc}"}), 500
    session.xlsx_path = path
    return jsonify({
        "ok": True,
        "file": path.name,
        "url": f"/api/download/{path.name}",
        "rows": len(session.rows),
    })


@app.get("/api/download/<path:name>")
def api_download(name: str):
    path = _safe_path(name)
    if path is None:
        return jsonify({"ok": False, "error": "Fichero no encontrado."}), 404
    return send_file(path, as_attachment=True)


@app.get("/api/sesiones")
def api_sesiones():
    """Lista los ficheros generados en la carpeta de sesiones."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (p for p in SESSIONS_DIR.iterdir() if p.is_file() and p.suffix.lower() in (".xlsx", ".csv")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:60]
    return jsonify({
        "ok": True,
        "files": [
            {
                "name": p.name,
                "url": f"/api/download/{p.name}",
                "size_kb": round(p.stat().st_size / 1024, 1),
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
                "kind": p.suffix.lower().lstrip("."),
            }
            for p in files
        ],
    })


def _run_demo(session: CaptureSession) -> None:
    """Ejecuta la demostración y finaliza la sesión igual que una captura real."""
    from demo import feed_demo

    try:
        feed_demo(session)
    finally:
        session._close_files()
        try:
            session.xlsx_path = export_session(session)
        except Exception as exc:  # noqa: BLE001
            session.error = f"No se pudo generar el Excel: {exc}"
        session.state = "stopped"
        session.stopped_at = datetime.now()
        session.message = "Demostración finalizada · datos simulados"
        session._publish({"type": "status", "status": session.status()})


@app.post("/api/demo")
def api_demo():
    """Modo demostración: inyecta eventos sintéticos por los handlers reales.

    Sirve para validar la interfaz, el CSV y el Excel sin depender de que haya
    un directo en vivo en ese momento.
    """
    global CURRENT

    from demo import DEMO_ROOM_ID, DEMO_USER

    with _REGISTRY_LOCK:
        active = CURRENT
        if active is not None and active.state in ("connecting", "live", "stopping"):
            return jsonify({"ok": False, "error": "Detén la captura en curso antes de la demo."}), 409
        session = CaptureSession(DEMO_USER, capture_gifts=True)
        session.state = "live"
        session.message = "Modo demostración (datos simulados)"
        session.room_id = DEMO_ROOM_ID
        session._open_csv()
        session.started_at = datetime.now()
        SESSIONS[session.session_id] = session
        CURRENT = session

    threading.Thread(target=_run_demo, args=(session,), daemon=True).start()
    return jsonify({"ok": True, "status": session.status()})


def main() -> None:
    parser = argparse.ArgumentParser(description="Captura de comentarios de TikTok LIVE")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print("=" * 62)
    print("  CAPTURA DE COMENTARIOS - TIKTOK LIVE")
    print("=" * 62)
    print(f"  Interfaz web : {url}")
    print(f"  Sesiones en  : {SESSIONS_DIR}")
    print("  Detén el servidor con Ctrl+C")
    print("=" * 62)

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # threaded=True es imprescindible: el SSE ocupa una conexión permanente.
    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    sys.exit(main())
