"""
Genera las capturas de pantalla que ilustran el README.

No son imágenes de diseño ni montajes: arranca la aplicación de verdad, la
puebla con el modo de demostración y fotografía la interfaz tal cual queda.

Requiere Playwright (no está en requirements.txt porque solo hace falta para
regenerar la documentación):

    .venv/Scripts/python.exe -m pip install playwright

Y un navegador. Por defecto reutiliza el Chrome que descarga `agent-browser` si
lo encuentra; si no, hay que indicar la ruta con --chrome o instalar Chromium con
`python -m playwright install chromium`.

Uso:
    .venv/Scripts/python.exe tools/screenshots.py
    .venv/Scripts/python.exe tools/screenshots.py --comments 24 --out docs
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

CHROME_CANDIDATES = [
    Path.home() / ".agent-browser" / "browsers",
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
]


def find_chrome(explicit: str | None) -> str | None:
    """Localiza un ejecutable de Chrome/Chromium para no descargar otro."""
    if explicit:
        return explicit
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
        if candidate.is_dir():
            found = sorted(candidate.glob("*/chrome.exe")) + sorted(candidate.glob("chrome.exe"))
            if found:
                return str(found[0])
    return None


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def frame_height(page, selector: str, margin: int = 26) -> int:
    """Altura de recorte que termina justo debajo del elemento indicado.

    Sin esto la captura corta a mitad de una línea del pie de página, porque la
    vista siempre es más corta que el documento entero.
    """
    box = page.locator(selector).first.bounding_box()
    if not box:
        return 0
    return int(box["y"] + box["height"] + margin)


def wait_for_comments(page, minimum: int, timeout: float = 90.0) -> int:
    """Espera a que la tabla tenga suficientes filas para una captura decente."""
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        count = page.locator("tbody tr.row").count()
        if count >= minimum:
            return count
        page.wait_for_timeout(500)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Capturas del README")
    parser.add_argument("--out", default="docs", help="carpeta de destino")
    parser.add_argument("--comments", type=int, default=22, help="comentarios a esperar antes de disparar")
    parser.add_argument("--chrome", default=None, help="ruta a chrome.exe")
    parser.add_argument(
        "--clean-sessions",
        action="store_true",
        help="borra las salidas de demostraciones anteriores antes de capturar, "
             "para que el panel de ficheros salga limpio. Solo elimina ficheros "
             "cuyo nombre contiene 'demo_simulado': nunca capturas reales.",
    )
    parser.add_argument("--keep-server", action="store_true", help="no detener el servidor al acabar")
    args = parser.parse_args()

    if args.clean_sessions:
        sessions_dir = BASE_DIR / "sesiones"
        removed = 0
        for path in sessions_dir.glob("*demo_simulado*"):
            path.unlink(missing_ok=True)
            removed += 1
        print(f"Salidas de demostración eliminadas: {removed}")

    out_dir = (BASE_DIR / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    python = str(BASE_DIR / ".venv" / "Scripts" / "python.exe")
    if not Path(python).exists():
        python = sys.executable

    print(f"Arrancando la aplicación en {url} ...")
    server = subprocess.Popen(
        [python, str(BASE_DIR / "app.py"), "--port", str(port), "--no-browser"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    chrome = find_chrome(args.chrome)
    print(f"Navegador: {chrome or 'Chromium de Playwright'}")

    try:
        if not wait_for_server(url):
            print("ERROR: el servidor no respondio a tiempo.")
            return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launch = {"headless": True, "args": ["--hide-scrollbars"]}
            if chrome:
                launch["executable_path"] = chrome
            browser = playwright.chromium.launch(**launch)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000},
                device_scale_factor=2,
                locale="es-ES",
            )
            page.goto(url, wait_until="load")
            page.wait_for_timeout(1200)

            # Poblar con el modo de demostración: mismos manejadores que un directo real.
            page.click("#btnDemo")
            print(f"Generando datos simulados hasta {args.comments} comentarios ...")
            count = wait_for_comments(page, args.comments)
            print(f"Comentarios en pantalla: {count}")

            # 1. Vista general con la captura en marcha.
            page.wait_for_timeout(600)
            height = frame_height(page, "main > section.card:nth-of-type(2)", 24)
            shot = out_dir / "interfaz-principal.png"
            page.screenshot(path=str(shot), clip={
                "x": 0, "y": 0, "width": 1440, "height": height,
            })
            print(f"  -> {shot.relative_to(BASE_DIR)}  (recorte {height}px)")

            # 2. Panel de detalle: se desactiva el autodesplazamiento para poder
            #    clicar una fila sin que la vista salte al final, y se agranda la
            #    ventana porque la rejilla de los 26 campos es alta.
            page.uncheck("#autoscroll")
            page.set_viewport_size({"width": 1440, "height": 1320})
            page.eval_on_selector("#tableScroll", "el => el.scrollTop = 0")
            page.wait_for_timeout(400)
            page.locator("tbody tr.row").nth(2).click()
            page.wait_for_timeout(500)
            height = frame_height(page, "tr.detail", 24)
            shot = out_dir / "detalle-comentario.png"
            page.screenshot(path=str(shot), clip={
                "x": 0, "y": 0, "width": 1440, "height": height,
            })
            print(f"  -> {shot.relative_to(BASE_DIR)}  (recorte {height}px)")

            # 3. Filtros en acción (suscriptores) con la barra lateral a la vista.
            page.locator("tbody tr.row").nth(2).click()  # cerrar el detalle
            page.wait_for_timeout(300)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.click('.chip[data-filter="sub"]')
            page.wait_for_timeout(600)
            height = frame_height(page, "main > section.card:nth-of-type(2)", 24)
            shot = out_dir / "filtros.png"
            page.screenshot(path=str(shot), clip={
                "x": 0, "y": 0, "width": 1440, "height": height,
            })
            print(f"  -> {shot.relative_to(BASE_DIR)}  (recorte {height}px)")

            browser.close()

    finally:
        if not args.keep_server:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    print("Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
