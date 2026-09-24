# MisFondos

Seguimiento gráfico de fondos indexados (o ETFs) en los que inviertes a través de MyInvestor u otro bróker, sin introducir tus credenciales en ningún sitio: los datos de precio se obtienen por ISIN a través de fuentes públicas (Yahoo Finance).

## Uso

1. Ejecuta `MisFondos.exe` (o `python run.py` si trabajas desde el código fuente).
2. Pulsa **+ Añadir fondo**, introduce el ISIN del fondo (lo encuentras en la ficha del fondo en MyInvestor) y pulsa **Buscar**.
3. Selecciona el resultado correcto de la lista y pulsa **Añadir seleccionado**. Se le asigna un color automáticamente.
4. Con **Ver juntas 1** ves la gráfica de un solo fondo (selecciónalo en la lista de la izquierda), con la subida/bajada de su último valor liquidativo y el botón **Mis aportaciones**. En **Vista global** ves todos los fondos superpuestos, cada uno con su color. Al pasar el ratón por una gráfica sale una raya vertical y un bocadillo con la fecha y el valor de ese punto.
5. La casilla **Normalizar (base 100)** en la vista global reescala cada fondo para que todos empiecen en 100, así se pueden comparar rendimientos aunque tengan precios muy distintos. Desmárcala para ver los precios reales.
6. Los botones de periodo (1M, 3M, 6M, YTD, 1A, Todo) filtran el rango de fechas mostrado.
   A continuación, **Ver juntas 1 · 2 · 3 · 4 · 5 · 6**: el 1 es la vista de un fondo (punto 4); del 2 al 6 se ven a la vez las 2 a 6 primeras gráficas de la lista, cada una con su rentabilidad en el periodo elegido. Con 2 van una encima de otra; con un número par todas ocupan lo mismo; con uno impar, la que más rentabilidad da en ese periodo sale el doble de grande (columna izquierda entera) y el resto se reparte a partes iguales. Si hay menos fondos que gráficas pedidas, se muestran los que haya.
7. **Actualizar ahora** fuerza una descarga inmediata. La app también se actualiza sola cada 15 minutos mientras está en marcha (editable en `misfondos/config.py`, variable `REFRESH_INTERVAL_SECONDS`).
8. **Junto al reloj de Windows**: al cerrar con la X, MisFondos sigue funcionando en el área de notificación (su icono muestra el valor de la cartera). Clic en el icono para abrirlo; clic derecho → **Salir** para cerrarlo del todo. En **⚙ Configuración → Inicio y reloj** se puede activar **Arrancar con Windows** (se abre escondido junto al reloj) o hacer que la X cierre del todo. Si lo abres estando ya en marcha, se muestra la ventana existente en vez de abrir otra copia.
9. **Alertas de caídas**: en **⚙ Configuración → Alertas de caídas** eliges a partir de qué bajada te avisa Windows, en un día (último valor liquidativo frente al anterior: 1, 2, 3 o 5 %) o en una semana (frente al de hace 7 días: 3, 5, 8 o 10 %). Se comprueban tras cada actualización para los fondos del usuario activo; cada caída avisa una sola vez (la semanal, como mucho una vez por semana y fondo). **Enviar aviso de prueba** muestra cómo se ven, y debajo aparecen los últimos avisos.

Los fondos indexados solo publican un valor liquidativo (VL) una vez al día, así que "tiempo real" aquí significa que la app detecta y añade el nuevo dato en cuanto el proveedor lo publica, no un streaming continuo de precios.

## Datos

- Cada usuario tiene su carpeta `data/users/<id>/` con su lista de fondos (`funds.json`), sus aportaciones (`portfolio.json`) y su tema (`settings.json`); `data/users.json` guarda la lista de usuarios y el activo.
- El histórico de cada fondo se cachea en `data/history/<ISIN>.csv` (común a todos los usuarios).
- `data/app_settings.json` guarda los ajustes del programa (si la X lo deja junto al reloj). El arranque con Windows se guarda en el registro (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valor `MisFondos`).
- `data/misfondos_log.txt` es el registro interno de errores y eventos.
- Al ejecutar el `.exe`, esta carpeta `data/` se crea junto al propio `.exe`, así que puedes mover el `.exe` a cualquier carpeta (USB, escritorio, etc.) y sus datos van con él.

## Desarrollo

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python run.py
```

## Generar el .exe

```powershell
.\build_exe.ps1
```

El ejecutable se genera en `dist\MisFondos.exe` (no necesita Python instalado en el ordenador donde se ejecute).
