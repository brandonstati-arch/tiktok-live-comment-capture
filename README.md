# Captura de comentarios de TikTok LIVE

Aplicación de escritorio con interfaz web local que **captura en tiempo real los
comentarios de un directo de TikTok**, guarda el texto, la hora exacta de
publicación y toda la información disponible del autor, y **exporta el resultado
a Excel** con cada campo en su columna.

Pensada para quien necesita analizar la conversación de un directo: investigación
de audiencia, moderación, análisis de sentimiento, detección de preguntas
frecuentes o simplemente conservar un chat que TikTok **no almacena**.

> El chat de un directo no se guarda en TikTok. Si no lo capturas en directo, se
> pierde. Esta herramienta existe para no perderlo.

---

## Índice

- [Características principales](#características-principales)
- [Requisitos](#requisitos)
- [Inicio rápido](#inicio-rápido)
- [Uso desde la línea de comandos](#uso-desde-la-línea-de-comandos)
- [Datos capturados](#datos-capturados)
- [Ficheros de salida](#ficheros-de-salida)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Cómo funciona](#cómo-funciona)
- [Verificación](#verificación)
- [Limitaciones y avisos legales](#limitaciones-y-avisos-legales)
- [Licencia](#licencia)

---

## Características principales

- **Captura en vivo** de comentarios mediante la conexión WebSocket del directo,
  con los eventos apareciendo en pantalla según llegan (Server-Sent Events).
- **Hora exacta de publicación** tomada del servidor de TikTok, con precisión de
  milisegundos, más la **latencia de recepción** calculada para cada mensaje.
- **Identificación del autor**: usuario, nombre visible, ID numérico, Sec UID y
  enlace directo al perfil.
- **Rol y contexto de cada participante**: moderador, suscriptor, seguidor,
  seguimiento mutuo, amigo, top gifter, nivel de miembro, nivel de gifter e
  insignias.
- **Sin pérdida de datos**: se escribe un CSV en disco fila a fila con `flush()`,
  de modo que un corte del proceso no se lleva por delante la sesión.
- **Excel generado automáticamente** al detener la captura, además de poder
  exportarse a demanda. Cuatro hojas: comentarios, usuarios agregados, resumen y
  regalos.
- **Deduplicación por identificador real de mensaje** (`msg_id`), no por texto:
  hay usuarios que repiten el mismo mensaje a propósito y no deben descartarse.
- **Interfaz con filtros**: búsqueda libre, filtro por suscriptores, moderadores y
  menciones, y panel de detalle con los 26 campos de cualquier comentario.
- **Modo demostración** con datos simulados, para probar la aplicación completa
  sin necesidad de que haya un directo en vivo en ese momento.
- **Iniciador de doble clic** (`INICIAR.bat`) que prepara el entorno la primera
  vez y arranca la aplicación abriendo el navegador solo.
- **Modo consola** para sesiones largas, sin navegador abierto.

---

## Requisitos

- **Python 3.10 o superior** (probado en 3.13).
- Windows para el iniciador `.bat`; en Linux o macOS se arranca a mano (ver más abajo).
- Conexión a internet.
- No necesita GPU ni clave de API.

---

## Inicio rápido

1. **Doble clic en `INICIAR.bat`.**

   La primera vez crea el entorno virtual e instala las dependencias (tarda un
   minuto); las siguientes arranca directamente. El navegador se abre solo en
   `http://127.0.0.1:5000`.

2. Escribe el **usuario de TikTok** que está en directo (con o sin `@`).

3. Pulsa **Iniciar captura**. Los comentarios aparecen en vivo con su hora exacta
   y su autor.

4. Pulsa **Detener** (o espera a que termine el directo). El Excel se genera solo
   y queda listado en el panel lateral.

Para cerrar la aplicación, `Ctrl+C` en la ventana de consola.

### Probar sin un directo en vivo

Pulsa **Probar con datos de ejemplo** en la interfaz. Se generan comentarios y
regalos simulados que recorren exactamente el mismo camino que los reales
(lectura de campos, escritura de CSV, exportación a Excel), así que sirve para
comprobar que todo funciona sin depender de que alguien esté emitiendo.

### En Linux o macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## Uso desde la línea de comandos

Para capturas largas, sin tener el navegador abierto:

```bash
# Captura normal (Ctrl+C detiene y genera el Excel)
.venv/Scripts/python.exe captura_cli.py @usuario

# Capturando también los regalos
.venv/Scripts/python.exe captura_cli.py @usuario --regalos

# Detener automáticamente tras 5 minutos
.venv/Scripts/python.exe captura_cli.py @usuario --segundos 300

# Datos simulados, sin conexión a TikTok
.venv/Scripts/python.exe captura_cli.py --demo
```

En Linux o macOS, sustituye `.venv/Scripts/python.exe` por `.venv/bin/python`.

---

## Datos capturados

Cada comentario se guarda con **26 campos**. Estos son los encabezados exactos
que encontrarás en el Excel y en el CSV:

| # | Columna | Contenido |
|---|---|---|
| 1 | `Nº` | Índice secuencial dentro de la sesión |
| 2 | `Fecha` | Fecha de publicación (`AAAA-MM-DD`) |
| 3 | `Hora (HH:MM:SS)` | Hora de publicación |
| 4 | `Hora exacta (con ms)` | Hora de publicación con milisegundos |
| 5 | `Fecha-hora ISO 8601` | Marca temporal completa con zona horaria |
| 6 | `Timestamp Unix (ms)` | Marca temporal en milisegundos |
| 7 | `Latencia recepción (ms)` | Retardo entre publicación y recepción |
| 8 | `Usuario (@)` | Nombre de usuario (`@handle`) |
| 9 | `Nombre visible` | Nombre mostrado en el directo |
| 10 | `ID del autor` | Identificador numérico del usuario |
| 11 | `Sec UID` | Identificador interno estable de la cuenta |
| 12 | `Comentario` | Texto del mensaje |
| 13 | `Idioma` | Idioma detectado del comentario |
| 14 | `ID del mensaje` | Identificador único del mensaje (deduplicación) |
| 15 | `Moderador` | `Sí` si es moderador del directo |
| 16 | `Suscriptor` | `Sí` si está suscrito al canal |
| 17 | `Seguidor` | `Sí` si sigue al creador |
| 18 | `Seguimiento mutuo` | `Sí` si hay seguimiento mutuo |
| 19 | `Amigo` | `Sí` si tiene la insignia de amistad |
| 20 | `Top gifter` | `Sí` si está en el ranking de regalos |
| 21 | `Nivel de miembro` | Nivel en el club de fans |
| 22 | `Nivel de gifter` | Nivel de usuario por regalos enviados |
| 23 | `Insignias` | Todas las insignias, con su nivel |
| 24 | `Menciones` | Usuarios mencionados con `@` |
| 25 | `Perfil` | Enlace al perfil de TikTok |
| 26 | `Sala (room_id)` | Identificador de la sala del directo |

Las columnas 2 a 6 son distintas representaciones del **mismo instante**: el de
publicación según el servidor de TikTok. Si por lo que sea el servidor no envía
esa marca, se usa la hora local de recepción.

---

## Ficheros de salida

Todo se guarda en la carpeta `sesiones/` (excluida del control de versiones, porque
contiene datos personales).

### CSV en vivo

`comentarios_<usuario>_<AAAAMMDD_HHMMSS>.csv`

Se escribe **fila a fila mientras dura la captura**, con `flush()` tras cada
línea. Si el proceso se cae o lo matas, conservas todo lo capturado hasta ese
instante. Codificado en `utf-8-sig` para que Excel abra bien los acentos.

### Excel final

`tiktok_<usuario>_<AAAAMMDD_HHMMSS>.xlsx`

Se genera automáticamente al detener la captura. Contiene cuatro hojas:

| Hoja | Contenido |
|---|---|
| **Comentarios** | Una fila por comentario, las 26 columnas, con autofiltro, panel congelado y enlaces al perfil |
| **Usuarios** | Agregado por autor: número de comentarios, primer y último mensaje, rol y nivel |
| **Resumen** | Metadatos de la sesión (usuario, sala, duración, totales, comentarios por minuto) y ranking de participantes |
| **Regalos** | Solo si se activó «Capturar regalos»: regalo, diamantes unitarios, repeticiones y total |

El fichero `EJEMPLO_salida.xlsx` incluido en el repositorio es una muestra
generada con datos ficticios, para que puedas ver el formato sin ejecutar nada.

---

## Estructura del proyecto

```
.
├── INICIAR.bat            # Iniciador de doble clic (Windows)
├── app.py                 # Servidor Flask y API (SSE, exportación, descargas)
├── capturer.py            # Motor de captura: conexión, deduplicación, escritura
├── exporter.py            # Generación del libro Excel
├── demo.py                # Generador de eventos sintéticos
├── captura_cli.py         # Modo consola
├── autotest.py            # Autoprueba del pipeline completo
├── introspect_proto.py    # Utilidad para inspeccionar el proto instalado
├── templates/index.html   # Interfaz
├── static/
│   ├── app.js             # Lógica de la interfaz y cliente SSE
│   └── style.css          # Estilos
├── sesiones/              # Salidas (ignorada por git)
└── requirements.txt
```

---

## Cómo funciona

### Captura

La API oficial de TikTok **no expone el chat de los directos**: ni la Display API
ni la Research API. La vía viable es el WebSocket interno del directo, al que se
accede con la librería [`TikTokLive`](https://github.com/isaackogan/TikTokLive).
TikTok exige una firma criptográfica en la URL de conexión; la librería la delega
en [Euler Stream](https://www.eulerstream.com), cuyo nivel comunitario es gratuito
(2.500 peticiones al día, de sobra para esto).

### Arquitectura

El motor de captura corre un **event loop de asyncio en su propio hilo**, porque
la librería es asíncrona y Flask es síncrono. Ambos se comunican exclusivamente a
través de colas: el hilo de captura publica eventos, y el servidor los reenvía al
navegador por **Server-Sent Events** (`/api/stream`).

El primer evento del flujo es una *instantánea* con el estado completo; a partir
de ahí solo viajan los comentarios nuevos. Así, si el navegador se reconecta, no
pierde nada y no hace falta sondear el servidor.

### Detalles que importan

- **Deduplicación por `msg_id`**, nunca por `(usuario, texto)`. En una prueba real,
  deduplicar por texto descartaba 27 de 56 comentarios válidos.
- **Orden de parada**: primero se cancela el WebSocket y se espera a que termine,
  y solo después se cierran los ficheros. Al revés, el siguiente evento que llega
  revienta con `I/O operation on closed file`.
- **Escritura defensiva**: lectura de campos con accesos tolerantes a nulos, para
  que un cambio en el protocolo de TikTok no tumbe la captura.

### Nota sobre las insignias

`TikTokLive` 7.0.1 incorpora ayudantes para leer insignias (`get_all_badges`,
`member_level`, `gifter_level`, `is_moderator`, `is_friend`, `is_top_gifter`) que
**están rotos** contra la versión del protocolo que instala: buscan campos
(`badges`, `badge_scene`, `log_extra`) que en realidad se llaman `badge_list`,
`scene_type` y `privilege_log_extra`. El resultado es que devuelven vacío o
`False` para todo el mundo, en silencio.

Este proyecto **no los usa**: lee `badge_list` directamente. Si en el futuro
actualizas la librería, comprueba si ya lo arreglaron antes de dar por buenas las
columnas de nivel. Los detalles están en `introspect_proto.py`, que documenta cómo
inspeccionar el protocolo instalado en lugar de fiarse de la documentación.

---

## Verificación

El repositorio incluye una autoprueba que recorre el pipeline completo con
eventos sintéticos construidos con el protocolo real —sin necesidad de que haya
un directo en vivo— y comprueba el CSV y el Excel resultantes:

```bash
.venv/Scripts/python.exe autotest.py
```

Cubre la captura de comentarios y regalos, la deduplicación, la presencia y el
formato de los 26 campos, la detección de roles e insignias, la escritura del CSV,
la estructura del libro Excel y la conectividad con el servidor de firma. Salida
esperada:

```
RESULTADO: todas las comprobaciones pasaron.
```

---

## Limitaciones y avisos legales

**El chat no se puede recuperar.** TikTok no almacena el chat de un directo. Esta
herramienta solo captura lo que ocurre mientras está en ejecución; no hay forma de
obtener comentarios de un directo ya terminado.

**Vía no oficial.** La captura se apoya en el WebSocket interno de TikTok, que sus
términos de servicio no contemplan como canal oficial. El riesgo real es el bloqueo
temporal de la IP o de la cuenta, no una consecuencia legal directa por el mero
hecho de leer. Úsalo bajo tu responsabilidad.

**Datos personales.** Los nombres de usuario, identificadores y comentarios son
datos personales. Si vas a almacenarlos, analizarlos o publicarlos, necesitas una
base legal para ello conforme al RGPD (en la Unión Europea) o la normativa
equivalente de tu jurisdicción, además de informar sobre la finalidad y el plazo de
conservación. La carpeta `sesiones/` está excluida del control de versiones
precisamente para reducir el riesgo de publicar esos datos por accidente.

**Límite de peticiones.** El nivel gratuito de Euler Stream permite 2.500
peticiones al día. Si tras muchas pruebas ves errores de *rate limit*, espera unos
minutos: no es un fallo de conexión ni una cuenta inexistente. Con una clave de API
de Euler Stream los límites son más altos.

**Nombres de usuario.** Escribe la cuenta tal y como aparece en TikTok. Si el
usuario no está en directo en ese momento, la aplicación lo indica explícitamente
en lugar de fallar en silencio.

---

## Licencia

Distribuido bajo la licencia **MIT**. Consulta el fichero [LICENSE](LICENSE).

La licencia cubre el código de este repositorio; no otorga ningún derecho sobre
los datos que captures con él ni sobre la plataforma TikTok.
