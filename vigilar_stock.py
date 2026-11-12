"""
Bot que vigila productos de dbs.cl y avisa cuando vuelven a tener stock.

Uso:
    python vigilar_stock.py            -> revisa una vez (ideal para el Programador de tareas)
    python vigilar_stock.py --loop     -> se queda revisando cada N minutos (config.json)
    python vigilar_stock.py --test     -> manda una notificación de prueba
    python vigilar_stock.py --estado   -> muestra el estado actual de cada producto

Configuración en config.json (misma carpeta que este archivo).
Solo usa la librería estándar de Python: no hay que instalar nada.
"""

import argparse
import base64
import html
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
CONFIG = CARPETA / "config.json"
ESTADO = CARPETA / "estado.json"
LOG = CARPETA / "registro.log"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Valores de schema.org que significan "se puede comprar"
DISPONIBLE = {"instock", "limitedavailability", "preorder", "presale", "onlineonly", "backorder"}

CONFIG_INICIAL = {
    "productos": [
        "https://dbs.cl/maquillaje-sets-twist-n-twinkle-holiday-calendario-de-adviento",
        "https://dbs.cl/calendario-adviento-the-beauty-journey-2026",
    ],
    "minutos_entre_revisiones": 10,
    "notificacion_windows": True,
    # Para recibir avisos en el celular: instala la app "ntfy" y suscríbete a este tema.
    "ntfy_tema": "",
    "ntfy_servidor": "https://ntfy.sh",
    # Aviso por correo: se envía desde tu propio Gmail hacia ti mismo.
    # Necesita una "contraseña de aplicación" de Google (16 letras), ver LEEME.md.
    "correo": "",
    "gmail_clave_app": "",
}


# ---------------------------------------------------------------- utilidades

def log(msg: str) -> None:
    linea = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(linea)
    except Exception:
        pass  # pythonw no tiene consola
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
        # que el log no crezca para siempre
        if LOG.stat().st_size > 1_000_000:
            lineas = LOG.read_text(encoding="utf-8").splitlines()[-2000:]
            LOG.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    except Exception:
        pass


def leer_json(ruta: Path, por_defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return por_defecto
    except Exception as e:
        log(f"No pude leer {ruta.name}: {e}")
        return por_defecto


def guardar_json(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


EN_LA_NUBE = bool(os.environ.get("GITHUB_ACTIONS"))


def cargar_config() -> dict:
    cfg = dict(CONFIG_INICIAL)
    if CONFIG.exists():
        cfg.update(leer_json(CONFIG, {}))
    elif not EN_LA_NUBE:
        cfg["ntfy_tema"] = "dbs-stock-" + secrets.token_hex(5)
        guardar_json(CONFIG, cfg)
        log(f"Creé {CONFIG.name} con un tema ntfy nuevo: {cfg['ntfy_tema']}")

    # En GitHub los datos privados vienen de "secrets" (variables de entorno)
    for clave, variable in [("ntfy_tema", "NTFY_TEMA"), ("correo", "CORREO"),
                            ("gmail_clave_app", "GMAIL_CLAVE_APP")]:
        if os.environ.get(variable):
            cfg[clave] = os.environ[variable].strip()
    if EN_LA_NUBE:
        cfg["notificacion_windows"] = False
    return cfg


# ------------------------------------------------------------ revisar stock

def descargar(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "es-CL,es;q=0.9",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def revisar(url: str) -> dict:
    """Devuelve {'disponible': True/False/None, 'nombre': str, 'precio': int|None}."""
    pagina = descargar(url)
    nombre, precio, disponibilidad = None, None, None

    # 1) Datos estructurados (JSON-LD) que la tienda publica para Google
    for bloque in re.findall(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', pagina, re.S | re.I
    ):
        try:
            datos = json.loads(bloque.strip())
        except Exception:
            continue
        for item in datos if isinstance(datos, list) else [datos]:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            nombre = item.get("name") or nombre
            ofertas = item.get("offers") or {}
            for oferta in ofertas if isinstance(ofertas, list) else [ofertas]:
                if isinstance(oferta, dict):
                    disponibilidad = oferta.get("availability") or disponibilidad
                    precio = oferta.get("price") or precio

    # 2) Respaldo: buscar el texto directamente
    if not disponibilidad:
        m = re.search(r'"availability"\s*:\s*"([^"]+)"', pagina)
        if m:
            disponibilidad = m.group(1)

    if disponibilidad:
        valor = disponibilidad.replace("\\/", "/").rsplit("/", 1)[-1].lower()
        disponible = valor in DISPONIBLE
    elif "amxnotif-block" in pagina:
        # el formulario "avísame cuando llegue" solo aparece si está agotado
        disponible = False
    else:
        disponible = None  # no se pudo determinar

    if not nombre:
        m = re.search(r'<title>(.*?)</title>', pagina, re.S)
        nombre = html.unescape(m.group(1)).split("|")[0].strip() if m else url
    try:
        precio = int(float(precio)) if precio else None
    except (TypeError, ValueError):
        precio = None

    return {"disponible": disponible, "nombre": nombre, "precio": precio}


# ------------------------------------------------------------ notificaciones

def _xml(texto: str) -> str:
    return html.escape(str(texto), quote=True)


def notificar_windows(titulo: str, mensaje: str, url: str) -> None:
    toast = (
        f'<toast scenario="reminder" activationType="protocol" launch="{_xml(url)}">'
        f'<visual><binding template="ToastGeneric">'
        f'<text>{_xml(titulo)}</text><text>{_xml(mensaje)}</text>'
        f'</binding></visual>'
        f'<actions>'
        f'<action content="Ir a comprar" activationType="protocol" arguments="{_xml(url)}"/>'
        f'<action content="Cerrar" activationType="system" arguments="dismiss"/>'
        f'</actions>'
        f'<audio src="ms-winsoundevent:Notification.Looping.Alarm" loop="false"/>'
        f'</toast>'
    )
    toast_b64 = base64.b64encode(toast.encode("utf-8")).decode()
    ps = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xmlText = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{toast_b64}'))
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xmlText)
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($doc))
"""
    comando = base64.b64encode(ps.encode("utf-16-le")).decode()
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", comando],
        check=True, capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def notificar_celular(cfg: dict, titulo: str, mensaje: str, url: str) -> None:
    """Push al celular vía la app ntfy."""
    datos = {
        "topic": cfg["ntfy_tema"],
        "title": titulo,
        "message": mensaje,
        "click": url,
        "priority": 5,
        "tags": ["shopping_cart", "tada"],
        "actions": [{"action": "view", "label": "Ir a comprar", "url": url}],
    }
    req = urllib.request.Request(
        cfg["ntfy_servidor"].rstrip("/") + "/",
        data=json.dumps(datos).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "dbs-stock-bot"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def notificar_gmail(cfg: dict, titulo: str, mensaje: str, url: str) -> None:
    import smtplib
    from email.message import EmailMessage

    correo = cfg["correo"]
    msg = EmailMessage()
    msg["Subject"] = titulo
    msg["From"] = f"Bot stock DBS <{correo}>"
    msg["To"] = correo
    msg.set_content(f"{mensaje}\n\nComprar aquí: {url}\n")
    msg.add_alternative(
        f"<h2>{_xml(titulo)}</h2><p style='font-size:16px'>{_xml(mensaje)}</p>"
        f"<p><a href='{_xml(url)}' style='background:#d6006e;color:#fff;padding:12px 20px;"
        f"border-radius:6px;text-decoration:none;font-weight:bold'>Ir a comprar</a></p>",
        subtype="html",
    )
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(correo, cfg["gmail_clave_app"].replace(" ", ""))
        s.send_message(msg)


def avisar(cfg: dict, titulo: str, mensaje: str, url: str) -> None:
    if cfg.get("notificacion_windows", True):
        try:
            notificar_windows(titulo, mensaje, url)
            log("  -> notificación de Windows enviada")
        except Exception as e:
            log(f"  -> falló la notificación de Windows: {e}")

    if cfg.get("correo") and cfg.get("gmail_clave_app"):
        try:
            notificar_gmail(cfg, titulo, mensaje, url)
            log("  -> correo enviado (Gmail)")
        except Exception as e:
            log(f"  -> falló el correo por Gmail: {e}")
    elif cfg.get("correo"):
        log("  -> correo no enviado: falta 'gmail_clave_app' (ver LEEME.md)")

    if cfg.get("ntfy_tema"):
        try:
            notificar_celular(cfg, titulo, mensaje, url)
            log("  -> notificación al celular enviada (ntfy)")
        except Exception as e:
            log(f"  -> falló la notificación al celular: {e}")


# ----------------------------------------------------------------- programa

def formatear_precio(p) -> str:
    return f"${p:,.0f}".replace(",", ".") if p else ""


def una_revision(cfg: dict) -> int:
    """Revisa todos los productos. Devuelve cuántos no se pudieron leer."""
    estado = leer_json(ESTADO, {})
    original = json.dumps(estado, sort_keys=True)
    errores = 0
    for url in cfg["productos"]:
        try:
            info = revisar(url)
        except Exception as e:
            log(f"Error revisando {url}: {e}")
            errores += 1
            continue

        antes = estado.get(url, {}).get("disponible")
        ahora = info["disponible"]
        texto = {True: "DISPONIBLE", False: "agotado", None: "desconocido"}[ahora]
        log(f"{info['nombre']}: {texto} {formatear_precio(info['precio'])}")

        if ahora is None:
            errores += 1
            continue  # no cambiamos el estado si no se pudo leer
        if ahora and antes is not True:
            avisar(
                cfg,
                "¡Volvió el stock en DBS!",
                f"{info['nombre']} {formatear_precio(info['precio'])}".strip(),
                url,
            )
        previo = estado.get(url, {})
        cambio = previo.get("disponible") != ahora
        estado[url] = {
            "disponible": ahora,
            "nombre": info["nombre"],
            "precio": info["precio"],
            # "desde" solo cambia cuando cambia la disponibilidad, así el archivo
            # no se modifica en cada revisión (en GitHub eso sería un commit cada vez)
            "desde": datetime.now().isoformat(timespec="minutes") if cambio
                     else previo.get("desde", previo.get("revisado", "")),
        }
    if json.dumps(estado, sort_keys=True) != original:
        guardar_json(ESTADO, estado)
    return errores


def main() -> None:
    ap = argparse.ArgumentParser(description="Avisa cuando productos de dbs.cl vuelven a tener stock.")
    ap.add_argument("--loop", action="store_true", help="seguir revisando cada N minutos")
    ap.add_argument("--test", action="store_true", help="enviar una notificación de prueba")
    ap.add_argument("--estado", action="store_true", help="mostrar el último estado guardado")
    args = ap.parse_args()

    cfg = cargar_config()

    if args.test:
        avisar(cfg, "Prueba del bot de stock DBS",
               "Si ves esto, las notificaciones funcionan.", cfg["productos"][0])
        return

    if args.estado:
        for url, e in leer_json(ESTADO, {}).items():
            print(f"{'DISPONIBLE' if e['disponible'] else 'agotado':10}  {e['nombre']}  (desde {e.get('desde', '?')})")
        return

    if args.loop:
        minutos = max(1, int(cfg.get("minutos_entre_revisiones", 10)))
        log(f"Vigilando {len(cfg['productos'])} productos cada {minutos} min (Ctrl+C para salir)")
        while True:
            una_revision(cfg)
            time.sleep(minutos * 60)
            cfg = cargar_config()  # por si editaste config.json mientras corre
    else:
        errores = una_revision(cfg)
        # Si no se pudo leer ningún producto, terminar con error: en GitHub eso
        # hace que te llegue un correo de "workflow failed" y te enteras.
        if errores and errores == len(cfg["productos"]):
            sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
