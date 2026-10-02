# historial.py
# Lee la bitácora (registro.py) y arma el historial del tablero: partidos,
# tiempo de juego, encendidos, reinicios y la salud de cada encendido.
# Lo sirve pruebas.py en http://192.168.216.1/historial.
#
# Un partido va de un reset al siguiente (o hasta que se reinicia el
# tanteador o se apaga el tablero). El tiempo de juego se cuenta del primer
# punto al último: el reset a veces llega recién al día siguiente.
#
# La agrupación por día la hace el celular, en su hora local: la Pi está en
# hora de Londres y sin reloj propio; acá solo viajan instantes absolutos.

import json
import os
import threading

from registro import ENCENDIDO, ruta_registro

# Menos puntos que esto no es un partido: es alguien probando el control.
MIN_PUNTOS = 3
# Un toque que tarda más que esto en verse en pantalla es un toque lento.
LENTO_MS = 500

def _p95(valores):
    if not valores:
        return None
    v = sorted(valores)
    return v[min(len(v) - 1, int(len(v) * 0.95))]

class Historial:
    """Lee el archivo incrementalmente: cada consulta procesa solo las
    líneas nuevas, así la página no se vuelve lenta con meses de registro."""

    def __init__(self):
        self.lock = threading.Lock()
        self._empezar(None)

    def _empezar(self, ruta):
        self.ruta = ruta
        self.offset = 0
        self.encendidos = {}   # id de encendido -> resumen
        self.partidos = []     # cerrados
        self.abiertos = {}     # id de encendido -> partido en curso

    def _leer(self):
        ruta = ruta_registro()
        try:
            tam = os.path.getsize(ruta)
        except OSError:
            tam = 0
        if ruta != self.ruta or tam < self.offset:
            self._empezar(ruta)  # otro pendrive, o archivo nuevo
        if tam == self.offset:
            return
        with open(ruta, 'rb') as f:
            f.seek(self.offset)
            bloque = f.read(tam - self.offset)
        fin = bloque.rfind(b'\n') + 1   # una línea a medio escribir, para la próxima
        self.offset += fin
        for linea in bloque[:fin].splitlines():
            try:
                self._evento(json.loads(linea))
            except (ValueError, KeyError, TypeError):
                continue  # línea rota (corte de luz): se saltea

    def _encendido(self, ev):
        b = ev['b']
        e = self.encendidos.get(b)
        if e is None:
            e = self.encendidos[b] = {
                'b': b, 'm0': ev['m'], 'ts0': ev['ts'], 'm1': ev['m'],
                'relojes': [], 'arranques': 0, 'puntos': 0, 'lentos': 0,
                'lat_max': 0, 'ignorados': 0, 'trabados': 0, 'trabado_max': 0,
                'cortes_control': 0, 'cortes_mqtt': 0, 'mem_min': None,
                'temp_max': None, 'tension': 0, 'rssi_min': None}
        e['m1'] = max(e['m1'], ev['m'])
        return e

    def _cerrar(self, b, motivo):
        p = self.abiertos.pop(b, None)
        if p:
            p['motivo'] = motivo
            self.partidos.append(p)

    def _evento(self, ev):
        e = self._encendido(ev)
        tipo = ev['tipo']
        if tipo == 'arranque':
            e['arranques'] += 1
            # El tanteador arranca en 0 a 0: el partido en curso se perdió.
            self._cerrar(ev['b'], 'se reinició el programa')
        elif tipo == 'punto':
            lat = ev.get('cola_ms', 0) + ev.get('pintar_ms', 0)
            e['puntos'] += 1
            e['lat_max'] = max(e['lat_max'], lat)
            if lat > LENTO_MS:
                e['lentos'] += 1
            p = self.abiertos.get(ev['b'])
            if p is None:
                p = self.abiertos[ev['b']] = {
                    'b': ev['b'], 'm_ini': ev['m'], 'puntos': 0, 'restas': 0,
                    'lats': []}
            p['m_fin'] = ev['m']
            p['l'], p['v'] = ev['l'], ev['v']
            p['puntos' if ev['d'] > 0 else 'restas'] += 1
            p['lats'].append(lat)
        elif tipo == 'reset':
            p = self.abiertos.get(ev['b'])
            if p:
                p['l'], p['v'] = ev['l'], ev['v']
            self._cerrar(ev['b'], 'reset')
        elif tipo == 'ignorado':
            e['ignorados'] += 1
        elif tipo == 'trabado':
            e['trabados'] += 1
            e['trabado_max'] = max(e['trabado_max'], ev['seg'])
        elif tipo == 'control' and ev.get('estado') == 'perdido':
            e['cortes_control'] += 1
        elif tipo == 'mqtt' and ev.get('estado') == 'desconectado':
            e['cortes_mqtt'] += 1
        elif tipo == 'salud':
            if ev.get('mem') is not None:
                e['mem_min'] = ev['mem'] if e['mem_min'] is None else min(e['mem_min'], ev['mem'])
            if ev.get('temp') is not None:
                e['temp_max'] = max(e['temp_max'] or 0, ev['temp'])
            e['tension'] |= ev.get('thr') or 0
            if ev.get('rssi_min') is not None:
                e['rssi_min'] = ev['rssi_min'] if e['rssi_min'] is None else min(e['rssi_min'], ev['rssi_min'])
        elif tipo == 'reloj':
            e['relojes'].append((ev['m'], ev['despues'], ev.get('fuente')))

    @staticmethod
    def _base(e):
        """Hora de pared del instante del encendido (m = 0), y si es
        confiable. Una puesta en hora desde el celular manda sobre todo; si
        no hubo, se usa la mejor estimación disponible."""
        celular = [r for r in e['relojes'] if r[2] == 'celular']
        if celular:
            m, despues, _ = celular[-1]
            return despues - m, True
        if e['relojes']:
            m, despues, _ = e['relojes'][-1]
            return despues - m, False
        return e['ts0'] - e['m0'], False

    def datos(self):
        with self.lock:
            self._leer()
            bases = {b: self._base(e) for b, e in self.encendidos.items()}
            encendidos = []
            for b, e in self.encendidos.items():
                base, ok = bases[b]
                encendidos.append({
                    'ini': round(base), 'dur': round(e['m1']), 'hora_ok': ok,
                    'actual': b == ENCENDIDO,
                    **{k: e[k] for k in ('arranques', 'puntos', 'lentos',
                                         'lat_max', 'ignorados', 'trabados',
                                         'trabado_max', 'cortes_control',
                                         'cortes_mqtt', 'mem_min', 'temp_max',
                                         'tension', 'rssi_min')}})
            partidos = []
            abiertos = [dict(p, motivo='en juego' if b == ENCENDIDO
                             else 'se apagó el tablero')
                        for b, p in self.abiertos.items()]
            for p in self.partidos + abiertos:
                if p['l'] + p['v'] < MIN_PUNTOS:
                    continue
                base, ok = bases[p['b']]
                partidos.append({
                    'ini': round(base + p['m_ini']),
                    'dur': round(p['m_fin'] - p['m_ini']),
                    'l': p['l'], 'v': p['v'], 'restas': p['restas'],
                    'motivo': p['motivo'], 'hora_ok': ok,
                    'lat_p95': _p95(p['lats']), 'lat_max': max(p['lats']),
                    'lentos': sum(1 for x in p['lats'] if x > LENTO_MS)})
            encendidos.sort(key=lambda x: x['ini'], reverse=True)
            partidos.sort(key=lambda x: x['ini'], reverse=True)
            return {'encendidos': encendidos, 'partidos': partidos,
                    'min_puntos': MIN_PUNTOS, 'lento_ms': LENTO_MS,
                    'pendrive': bool(self.ruta) and self.ruta.startswith('/media/')}

PAGINA = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Historial del tablero</title>
<style>
  body { background: #111; color: #eee; font-family: sans-serif;
         max-width: 46em; margin: 0 auto; padding: 1em; }
  h1 { font-size: 1.3em; color: #ffbe00; }
  h2 { font-size: 1.05em; color: #ffbe00; margin-top: 1.6em; }
  p, small { color: #aaa; line-height: 1.4; }
  .tabla { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.92em; }
  th, td { padding: 0.4em 0.35em; text-align: right; border-bottom: 1px solid #333;
           white-space: nowrap; }
  th { color: #aaa; font-weight: normal; }
  th:first-child, td:first-child { text-align: left; }
  .mal { color: #f55; } .ojo { color: #f92; } .bien { color: #5d5; }
  .aviso { background: #3a2a00; color: #ffd27a; padding: 0.7em; border-radius: 0.5em; }
  a { color: #ffbe00; }
</style></head><body>
<h1>Historial del tablero</h1>
<div id="avisos"></div>

<h2>Por día</h2>
<div class="tabla"><table id="dias"><thead><tr>
<th>Día</th><th>Partidos</th><th>Tiempo de juego</th><th>Encendidos</th>
<th>Reinicios del programa</th><th>Toques lentos</th>
</tr></thead><tbody></tbody></table></div>

<h2>Partidos</h2>
<div class="tabla"><table id="partidos"><thead><tr>
<th>Inicio</th><th>Duración</th><th>Local</th><th>Visita</th><th>Restas</th>
<th>Terminó por</th><th>Toque más lento</th>
</tr></thead><tbody></tbody></table></div>

<h2>Encendidos (diagnóstico)</h2>
<div class="tabla"><table id="encendidos"><thead><tr>
<th>Encendido</th><th>Duró</th><th>Toques</th><th>Lentos</th><th>Más lento</th>
<th>Trabones</th><th>Cortes control</th><th>Señal peor</th><th>Mem. mín.</th>
<th>Temp. máx.</th><th>Tensión baja</th><th>Reinicios</th>
</tr></thead><tbody></tbody></table></div>

<p><small>
<b>Toque lento</b>: más de <span class="lento"></span>&nbsp;ms entre que llega
el toque y se ve en pantalla. <b>Trabón</b>: la pantalla estuvo congelada más
de 1,5&nbsp;s. <b>Corte del control</b>: el control dejó de reportar su señal
más de 15&nbsp;s. Los partidos con menos de <span class="minp"></span> puntos
no se cuentan. Las horas con <b>≈</b> son aproximadas: la Pi no tiene reloj y
nadie la puso en hora en ese encendido (abrir esta página desde el celular lo
hace solo).
</small></p>
<p><a href="/historial/registro.jsonl" download>Bajar la bitácora completa</a></p>

<script>
function fecha(s, ok) {
  const d = new Date(s * 1000);
  return (ok ? '' : '\\u2248 ') + d.toLocaleDateString('es-AR', {weekday: 'short', day: 'numeric', month: 'numeric'})
    + ' ' + d.toLocaleTimeString('es-AR', {hour: '2-digit', minute: '2-digit'});
}
function dia(s) {
  return new Date(s * 1000).toLocaleDateString('es-AR', {weekday: 'short', day: 'numeric', month: 'numeric', year: 'numeric'});
}
function dur(s) {
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h ? h + ' h ' + String(m).padStart(2, '0') + ' min' : m + ' min';
}
function celda(v, clase) { return '<td' + (clase ? ' class="' + clase + '"' : '') + '>' + v + '</td>'; }
function fila(tabla, celdas) {
  const tr = document.createElement('tr');
  tr.innerHTML = celdas.join('');
  document.querySelector('#' + tabla + ' tbody').appendChild(tr);
}

async function cargar() {
  // Poner la Pi en hora con la del celular: es su único reloj confiable.
  try { await fetch('/reloj', {method: 'POST', body: String(Date.now())}); } catch (e) {}
  const d = await (await fetch('/historial/datos')).json();
  document.querySelectorAll('.lento').forEach(e => e.textContent = d.lento_ms);
  document.querySelectorAll('.minp').forEach(e => e.textContent = d.min_puntos);
  if (!d.pendrive)
    document.getElementById('avisos').innerHTML = '<p class="aviso">\\u26a0\\ufe0f El pendrive no est\\u00e1 montado: '
      + 'lo de este encendido se guarda en RAM y se pierde al desenchufar.</p>';

  const dias = {};
  const de = k => dias[k] ||= {partidos: 0, juego: 0, encendidos: 0, reinicios: 0, lentos: 0};
  for (const p of d.partidos) {
    const x = de(dia(p.ini));
    x.partidos++; x.juego += p.dur;
  }
  for (const e of d.encendidos) {
    const x = de(dia(e.ini));
    x.encendidos++; x.reinicios += Math.max(0, e.arranques - 1); x.lentos += e.lentos;
  }
  const orden = [...d.partidos, ...d.encendidos].sort((a, b) => b.ini - a.ini).map(x => dia(x.ini));
  for (const k of [...new Set(orden)]) {
    const x = dias[k];
    fila('dias', [celda(k), celda(x.partidos), celda(dur(x.juego)), celda(x.encendidos),
                  celda(x.reinicios, x.reinicios ? 'ojo' : ''), celda(x.lentos, x.lentos ? 'mal' : '')]);
  }
  for (const p of d.partidos) {
    fila('partidos', [celda(fecha(p.ini, p.hora_ok)), celda(dur(p.dur)), celda(p.l), celda(p.v),
                      celda(p.restas), celda(p.motivo, p.motivo === 'reset' || p.motivo === 'en juego' ? '' : 'ojo'),
                      celda(p.lat_max + ' ms', p.lat_max > d.lento_ms ? 'mal' : '')]);
  }
  for (const e of d.encendidos) {
    fila('encendidos', [
      celda(fecha(e.ini, e.hora_ok) + (e.actual ? ' (ahora)' : '')), celda(dur(e.dur)), celda(e.puntos),
      celda(e.lentos, e.lentos ? 'mal' : ''), celda(e.lat_max + ' ms', e.lat_max > d.lento_ms ? 'mal' : ''),
      celda(e.trabados ? e.trabados + ' (' + e.trabado_max + ' s)' : 0, e.trabados ? 'mal' : ''),
      celda(e.cortes_control, e.cortes_control ? 'ojo' : ''),
      celda(e.rssi_min === null ? '\\u2014' : e.rssi_min, e.rssi_min !== null && e.rssi_min < -75 ? 'mal' : ''),
      celda(e.mem_min === null ? '\\u2014' : e.mem_min + ' MB', e.mem_min !== null && e.mem_min < 60 ? 'mal' : ''),
      celda(e.temp_max === null ? '\\u2014' : e.temp_max + ' \\u00b0C', e.temp_max > 75 ? 'mal' : ''),
      celda(e.tension ? 's\\u00ed (0x' + e.tension.toString(16) + ')' : 'no', e.tension ? 'mal' : ''),
      celda(Math.max(0, e.arranques - 1), e.arranques > 1 ? 'ojo' : '')]);
  }
}
cargar();
</script>
</body></html>
"""
