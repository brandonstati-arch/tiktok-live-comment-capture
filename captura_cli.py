"""
Captura de comentarios de TikTok LIVE sin interfaz web (modo consola).

Útil para sesiones largas: consume menos recursos que tener el navegador abierto.
Al pulsar Ctrl+C detiene la captura y genera el Excel.

Uso:
    .venv/Scripts/python.exe captura_cli.py @usuario
    .venv/Scripts/python.exe captura_cli.py @usuario --regalos
    .venv/Scripts/python.exe captura_cli.py @usuario --segundos 300
    .venv/Scripts/python.exe captura_cli.py --demo
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

from capturer import CaptureSession
from demo import feed_demo


def _drain(session: CaptureSession, stop: threading.Event) -> None:
    """Muestra por consola los comentarios que van llegando."""
    channel = session.subscribe()
    try:
        while not stop.is_set():
            try:
                payload = channel.get(timeout=0.5)
            except queue.Empty:
                continue
            if payload.get("type") == "comment":
                row = payload["row"]
                tags = " ".join(
                    label for key, label in (
                        ("es_moderador", "[MOD]"),
                        ("es_suscriptor", "[SUB]"),
                        ("es_top_gifter", "[TOP]"),
                    ) if row.get(key) == "Sí"
                )
                print(f"{row['hora_ms']}  {row['usuario']:<22} {tags:<12} {row['comentario']}")
            elif payload.get("type") == "gift":
                row = payload["row"]
                print(f"{row['hora_ms']}  {row['usuario']:<22} [REGALO]     "
                      f"{row['regalo']} x{row['repeticiones']} ({row['diamantes_totales']} diamantes)")
            elif payload.get("type") == "status":
                print(f"--- estado: {payload['status']['message']}")
    finally:
        session.unsubscribe(channel)


def main() -> int:
    parser = argparse.ArgumentParser(description="Captura de comentarios de TikTok LIVE (consola)")
    parser.add_argument("usuario", nargs="?", help="usuario de TikTok, con o sin @")
    parser.add_argument("--regalos", action="store_true", help="capturar tambien los regalos")
    parser.add_argument("--segundos", type=float, default=0, help="detener automaticamente tras N segundos")
    parser.add_argument("--demo", action="store_true", help="datos simulados, sin conexion a TikTok")
    args = parser.parse_args()

    if not args.demo and not args.usuario:
        parser.error("indica el usuario de TikTok o usa --demo")

    session = CaptureSession(args.usuario or "demo_simulado", capture_gifts=args.regalos or args.demo)

    stop = threading.Event()
    printer = threading.Thread(target=_drain, args=(session, stop), daemon=True)
    printer.start()

    if args.demo:
        session.state = "live"
        session.room_id = "0000000000000000000"
        session._open_csv()
        from datetime import datetime
        session.started_at = datetime.now()
        print("Modo demostracion: generando comentarios simulados...\n")
        feeder = threading.Thread(
            target=feed_demo,
            args=(session,),
            kwargs={"should_stop": stop.is_set},
            daemon=True,
        )
        feeder.start()
    else:
        print(f"Conectando con @{session.unique_id} ...\n")
        session.start()

    try:
        deadline = time.time() + args.segundos if args.segundos else None
        while True:
            if deadline is not None and time.time() >= deadline:
                print("\nTiempo de captura agotado: deteniendo...")
                break
            if args.demo:
                if not feeder.is_alive():
                    break
            elif session._thread is None or not session._thread.is_alive():
                break
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\nCtrl+C recibido: deteniendo...")

    stop.set()
    if not args.demo:
        session.stop()
        session.wait(20)
    time.sleep(0.4)

    # Cerrar los ficheros ANTES de exportar: si el hilo de la demo sigue vivo,
    # una escritura tardía reventaria con "I/O operation on closed file".
    session._close_files()
    if not session.xlsx_path and session.rows:
        from exporter import export_session
        session.xlsx_path = export_session(session)

    print("\n" + "=" * 60)
    print(f"Comentarios capturados : {len(session.rows)}")
    print(f"Usuarios unicos        : {session.stats()['unique_users']}")
    if session.gift_rows:
        print(f"Regalos capturados     : {len(session.gift_rows)}")
    if session.error:
        print(f"Aviso                  : {session.error}")
    print(f"CSV                    : {session.csv_path if session.csv_path.exists() else '(sin datos)'}")
    print(f"Excel                  : {session.xlsx_path or '(sin datos)'}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
