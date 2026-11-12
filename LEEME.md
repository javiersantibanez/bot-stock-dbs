# Bot de stock para dbs.cl

Revisa cada 10 minutos si los productos de `config.json` vuelven a tener stock y,
**solo cuando pasan de agotado a disponible**, te avisa por:

- **Correo** (desde tu propio Gmail hacia ti mismo)
- **Celular** (app gratuita *ntfy*, tema `dbs-stock-9a091480d9`)
- **Windows** (solo si lo corres en tu PC)

Para que funcione con el PC apagado, se corre gratis en **GitHub Actions**.

---

## Paso 1 — Contraseña de aplicación de Gmail (5 min)

Gmail no deja que un programa use tu clave normal; hay que crear una especial
solo para el bot. **No la compartas con nadie ni la pegues en un chat.**

1. Activa la verificación en 2 pasos (si ya la tienes, sáltate esto):
   <https://myaccount.google.com/signinoptions/twosv>
2. Entra a <https://myaccount.google.com/apppasswords>
3. Ponle de nombre `bot stock dbs` → **Crear**.
4. Copia las 16 letras que aparecen (ej. `abcd efgh ijkl mnop`). Se usan en el paso 2.5.

## Paso 2 — Subirlo a GitHub (10 min)

1. Crea una cuenta gratis en <https://github.com/signup> (si no tienes).
2. Crea un repositorio nuevo: <https://github.com/new>
   - Nombre: `bot-stock-dbs`
   - Visibilidad: **Public** (así los minutos son ilimitados y gratis;
     tu correo y claves NO quedan visibles porque van como *secrets*).
   - **Create repository**.
3. En la página del repo, haz clic en **uploading an existing file**, arrastra
   `vigilar_stock.py` y `config.json` (de la carpeta `para-github`) → **Commit changes**.
4. **Add file → Create new file**. En el nombre escribe exactamente:
   `.github/workflows/revisar-stock.yml`
   Pega el contenido del archivo `para-github/.github/workflows/revisar-stock.yml`
   → **Commit changes**.
5. **Settings → Secrets and variables → Actions → New repository secret**.
   Crea estos tres (nombre exacto a la izquierda):

   | Name              | Secret                              |
   |-------------------|-------------------------------------|
   | `CORREO`          | `javier.santibanez.93@gmail.com`    |
   | `GMAIL_CLAVE_APP` | las 16 letras del paso 1            |
   | `NTFY_TEMA`       | `dbs-stock-9a091480d9`              |

## Paso 3 — Probar

1. Pestaña **Actions** → **Revisar stock DBS** → **Run workflow** → **Run workflow**.
2. En 1 minuto debería llegarte un correo *"Prueba del bot de stock DBS"*
   y una notificación en el celular.
3. Listo: desde ahora corre solo cada 10 minutos, con el PC apagado.

Si el correo no llega: revisa la carpeta Spam y que `GMAIL_CLAVE_APP` esté bien copiada.
Si GitHub no puede leer dbs.cl, la ejecución sale en rojo y GitHub te manda un correo avisando.

---

## Agregar o quitar productos

Edita `config.json` (en GitHub: abre el archivo → ícono de lápiz → **Commit changes**)
y agrega el link del producto dentro de `"productos"`.

## Correrlo en tu PC (opcional)

```
python vigilar_stock.py          # revisa una vez
python vigilar_stock.py --loop   # revisa cada 10 min mientras la ventana esté abierta
python vigilar_stock.py --test   # manda una notificación de prueba
python vigilar_stock.py --estado # muestra el último estado
```

En el PC, la clave de Gmail va en `config.json` → `"gmail_clave_app"`.
