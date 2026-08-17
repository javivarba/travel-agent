"""Runner del harness de evals.

    python -m evals.runner --version v1 --n 3
    python -m evals.runner --casos 01_manzanillo_cobertura_baja --grabar
    python -m evals.runner --fixtures            # sin API, para iterar aserciones
    python -m evals.runner --comparar v1 v2

Por qué N corridas por caso: la salida del modelo varía entre llamadas
idénticas. Una corrida sola no es una medición, es una anécdota — dice si
pasó esa vez, no si el prompt es confiable. Con N=3 la resolución es
gruesa (0, 33, 67, 100%) pero ya distingue "falla siempre" de "falla a
veces", que es la distinción que importa al comparar versiones.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import anthropic

from app import agent
from app.models import RespuestaEventos, RespuestaInvestigacion
from evals import aserciones, juez
from evals.aserciones import Resultado, Severidad
from evals.casos import CASOS, POR_ID, Caso

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "evals" / "resultados"
FIXTURES = RAIZ / "tests" / "fixtures"

VERDE, ROJO, AMARILLO, GRIS, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


@dataclass
class Corrida:
    caso_id: str
    n: int
    ok: bool
    error: str | None = None
    resultados: list[Resultado] = field(default_factory=list)
    metricas: dict = field(default_factory=dict)
    juez: dict | None = None

    @property
    def paso(self) -> bool:
        return self.ok and all(
            r.paso for r in self.resultados if r.severidad is Severidad.bloqueante
        )

    def como_dict(self) -> dict:
        return {
            "caso_id": self.caso_id, "n": self.n, "ok": self.ok, "paso": self.paso,
            "error": self.error,
            "resultados": [r.como_dict() for r in self.resultados],
            "metricas": self.metricas, "juez": self.juez,
        }


# --------------------------------------------------------------------------
# Ejecución
# --------------------------------------------------------------------------

def _fusionar_metricas(*ms: agent.Metricas) -> dict:
    total = agent.Metricas()
    for m in ms:
        total.busquedas += m.busquedas
        total.tokens_entrada += m.tokens_entrada
        total.tokens_salida += m.tokens_salida
        total.tokens_cache_lectura += m.tokens_cache_lectura
        total.items_descartados_por_fuente += m.items_descartados_por_fuente
        total.items_totales += m.items_totales
    return total.como_dict()


def correr_caso(
    cliente: anthropic.Anthropic | None,
    caso: Caso,
    n: int,
    version: str,
    usar_juez: bool,
    grabar: bool,
    hoy: date,
) -> Corrida:
    if cliente is None:
        return _correr_desde_fixture(caso, n)

    inv = agent.investigar(
        cliente=cliente, lugar=caso.lugar, fecha_inicio=caso.fecha_inicio,
        fecha_fin=caso.fecha_fin, intereses=caso.intereses, fecha_actual=hoy,
        version_prompt=version, pais=caso.pais,
    )

    ev = None
    if caso.pide_eventos:
        ev = agent.buscar_eventos(
            cliente=cliente, lugar=caso.lugar, fecha_inicio=caso.fecha_inicio,
            fecha_fin=caso.fecha_fin, fecha_actual=hoy,
            version_prompt=version, pais=caso.pais,
        )

    metricas = _fusionar_metricas(inv.metricas, *( [ev.metricas] if ev else [] ))

    # El caso de destino inexistente invierte la expectativa: fallar es pasar.
    if caso.espera_error:
        vacio = inv.ok and inv.respuesta is not None and not (
            inv.respuesta.imprescindibles or inv.respuesta.segun_intereses
        )
        return Corrida(
            caso.id, n, ok=True, metricas=metricas,
            resultados=[Resultado(
                "falla_limpia_o_vacio", (not inv.ok) or vacio,
                detalle="devolvió actividades para un lugar inexistente"
                if not ((not inv.ok) or vacio) else (inv.error or "vacío, correcto"),
            )],
        )

    if not inv.ok:
        return Corrida(caso.id, n, ok=False, error=inv.error, metricas=metricas)

    if grabar:
        _grabar_fixture(caso, inv, ev)

    resultados = aserciones.evaluar_investigacion(caso, inv.respuesta, inv.urls_consultadas)
    if ev is not None:
        if not ev.ok:
            resultados.append(Resultado("llamada_eventos_ok", False, detalle=ev.error or ""))
        else:
            resultados += aserciones.evaluar_eventos(caso, ev.respuesta, ev.urls_consultadas)
    else:
        resultados += aserciones.evaluar_eventos(caso, RespuestaEventos(eventos=[]), set())

    fallo_juez = None
    if usar_juez:
        fallo_juez = juez.juzgar(cliente, caso, inv.respuesta).como_dict()

    return Corrida(caso.id, n, ok=True, resultados=resultados,
                   metricas=metricas, juez=fallo_juez)


def _grabar_fixture(caso: Caso, inv, ev) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    payload = {
        "caso_id": caso.id,
        "investigacion": inv.crudo,
        "urls_investigacion": sorted(inv.urls_consultadas),
        "eventos": ev.crudo if ev else None,
        "urls_eventos": sorted(ev.urls_consultadas) if ev else [],
    }
    (FIXTURES / f"{caso.id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _correr_desde_fixture(caso: Caso, n: int) -> Corrida:
    """Modo offline. Sirve para desarrollar aserciones sin gastar API —
    que es donde vas a pasar la mayor parte del tiempo."""
    ruta = FIXTURES / f"{caso.id}.json"
    if not ruta.exists():
        return Corrida(caso.id, n, ok=False, error=f"sin fixture: {ruta.name}")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    try:
        inv = RespuestaInvestigacion.model_validate(datos["investigacion"])
    except Exception as e:
        return Corrida(caso.id, n, ok=False, error=f"fixture inválido: {e}")

    urls_i = set(datos.get("urls_investigacion", []))
    resultados = aserciones.evaluar_investigacion(caso, inv, urls_i)
    ev_datos = datos.get("eventos")
    ev = RespuestaEventos.model_validate(ev_datos) if ev_datos else RespuestaEventos(eventos=[])
    resultados += aserciones.evaluar_eventos(caso, ev, set(datos.get("urls_eventos", [])))
    return Corrida(caso.id, n, ok=True, resultados=resultados)


# --------------------------------------------------------------------------
# Reporte
# --------------------------------------------------------------------------

def reportar(corridas: list[Corrida], n: int) -> dict:
    por_caso: dict[str, list[Corrida]] = {}
    for c in corridas:
        por_caso.setdefault(c.caso_id, []).append(c)

    print(f"\n{'CASO':<36} {'PASA':>7}  DETALLE")
    print("─" * 92)

    resumen_casos = {}
    for caso_id, cs in por_caso.items():
        pasaron = sum(1 for c in cs if c.paso)
        tasa = pasaron / len(cs)
        color = VERDE if tasa == 1 else (ROJO if tasa == 0 else AMARILLO)
        marca = f"{pasaron}/{len(cs)}"
        print(f"{caso_id:<36} {color}{marca:>7}{RESET}", end="  ")

        fallos: dict[str, int] = {}
        advertencias: dict[str, int] = {}
        for c in cs:
            if not c.ok:
                fallos[f"⚠ {c.error[:60] if c.error else 'error'}"] = \
                    fallos.get(f"⚠ {c.error[:60] if c.error else 'error'}", 0) + 1
            for r in c.resultados:
                if r.paso:
                    continue
                destino = fallos if r.severidad is Severidad.bloqueante else advertencias
                destino[r.nombre] = destino.get(r.nombre, 0) + 1

        print(", ".join(f"{k} ({v}/{len(cs)})" for k, v in fallos.items()) or "—")
        for k, v in advertencias.items():
            print(f"{'':<36} {GRIS}  adv: {k} ({v}/{len(cs)}){RESET}")

        notas = [c.juez["promedio"] for c in cs if c.juez and c.juez.get("ok")]
        resumen_casos[caso_id] = {
            "tasa_paso": round(tasa, 3),
            "fallos": fallos,
            "advertencias": advertencias,
            "juez_promedio": round(statistics.mean(notas), 2) if notas else None,
            "juez_desvio": round(statistics.pstdev(notas), 2) if len(notas) > 1 else None,
        }

    tasas = [v["tasa_paso"] for v in resumen_casos.values()]
    busquedas = sum(c.metricas.get("busquedas", 0) for c in corridas)
    costo = sum(c.metricas.get("costo_busqueda_usd", 0) for c in corridas)
    totales = sum(c.metricas.get("items_totales", 0) for c in corridas)
    descartados = sum(c.metricas.get("items_descartados_por_fuente", 0) for c in corridas)
    notas = [c.juez["promedio"] for c in corridas if c.juez and c.juez.get("ok")]

    print("─" * 92)
    print(f"Tasa de paso global      {statistics.mean(tasas):.0%}  "
          f"({sum(1 for t in tasas if t == 1)}/{len(tasas)} casos en verde siempre)")
    print(f"Tasa de descarte         {descartados / totales:.1%}"
          if totales else "Tasa de descarte         n/a")
    if notas:
        print(f"Juez (promedio)          {statistics.mean(notas):.2f}/5"
              + (f"  σ={statistics.pstdev(notas):.2f}" if len(notas) > 1 else ""))
    print(f"Búsquedas                {busquedas}  (~${costo:.2f})")

    return {
        "tasa_paso_global": round(statistics.mean(tasas), 3) if tasas else 0,
        "tasa_descarte": round(descartados / totales, 4) if totales else None,
        "juez_promedio": round(statistics.mean(notas), 2) if notas else None,
        "busquedas": busquedas,
        "costo_busqueda_usd": round(costo, 2),
        "casos": resumen_casos,
    }


def comparar(v1: str, v2: str) -> None:
    """Compara la última corrida de dos versiones de prompt. Sin esto,
    'mejoré el prompt' es una opinión."""
    def ultimo(v: str) -> dict | None:
        archivos = sorted(RESULTADOS.glob(f"{v}_*.json"))
        return json.loads(archivos[-1].read_text(encoding="utf-8")) if archivos else None

    a, b = ultimo(v1), ultimo(v2)
    if not a or not b:
        sys.exit(f"Falta la corrida de {v1 if not a else v2}")

    print(f"\n{'CASO':<36} {v1:>8} {v2:>8}   Δ")
    print("─" * 66)
    for caso_id in sorted(set(a["resumen"]["casos"]) | set(b["resumen"]["casos"])):
        ta = a["resumen"]["casos"].get(caso_id, {}).get("tasa_paso", 0)
        tb = b["resumen"]["casos"].get(caso_id, {}).get("tasa_paso", 0)
        d = tb - ta
        color = VERDE if d > 0 else (ROJO if d < 0 else GRIS)
        print(f"{caso_id:<36} {ta:>7.0%} {tb:>7.0%}   {color}{d:+.0%}{RESET}")
    print("─" * 66)
    for etiqueta, clave, mejor_alto in [
        ("Tasa de paso", "tasa_paso_global", True),
        ("Tasa de descarte", "tasa_descarte", False),
        ("Juez", "juez_promedio", True),
    ]:
        va, vb = a["resumen"].get(clave), b["resumen"].get(clave)
        if va is None or vb is None:
            continue
        d = vb - va
        bien = (d > 0) if mejor_alto else (d < 0)
        color = VERDE if d and bien else (ROJO if d else GRIS)
        print(f"{etiqueta:<36} {va:>7.2f} {vb:>7.2f}   {color}{d:+.2f}{RESET}")


# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Harness de evals del agente de viajes")
    p.add_argument("--version", default="v1", help="versión de prompt a evaluar")
    p.add_argument("--n", type=int, default=3, help="corridas por caso (varianza)")
    p.add_argument("--casos", nargs="*", help="ids de casos; por defecto todos")
    p.add_argument("--sin-juez", action="store_true", help="omite la evaluación subjetiva")
    p.add_argument("--fixtures", action="store_true", help="modo offline, sin API")
    p.add_argument("--grabar", action="store_true", help="guarda las respuestas como fixtures")
    p.add_argument("--hoy", type=date.fromisoformat, default=date.today(),
                   help="fecha de referencia inyectada al prompt")
    p.add_argument("--comparar", nargs=2, metavar=("V1", "V2"))
    args = p.parse_args()

    if args.comparar:
        comparar(*args.comparar)
        return

    casos = [POR_ID[c] for c in args.casos] if args.casos else CASOS
    n = 1 if args.fixtures else args.n
    cliente = None if args.fixtures else anthropic.Anthropic()

    if not args.fixtures:
        estimado = len(casos) * n * 10 * agent.COSTO_POR_BUSQUEDA_USD
        print(f"{len(casos)} casos × {n} corridas — costo estimado de búsqueda ~${estimado:.2f}")

    corridas: list[Corrida] = []
    for caso in casos:
        for i in range(1, n + 1):
            print(f"{GRIS}  {caso.id} [{i}/{n}]{RESET}", flush=True)
            corridas.append(correr_caso(
                cliente, caso, i, args.version,
                usar_juez=not args.sin_juez and not args.fixtures,
                grabar=args.grabar and i == 1,
                hoy=args.hoy,
            ))

    resumen = reportar(corridas, n)

    if not args.fixtures:
        RESULTADOS.mkdir(parents=True, exist_ok=True)
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = RESULTADOS / f"{args.version}_{sello}.json"
        ruta.write_text(json.dumps({
            "version_prompt": args.version,
            "fecha": datetime.now().isoformat(),
            "n_por_caso": n,
            "fecha_referencia": args.hoy.isoformat(),
            "resumen": resumen,
            "corridas": [c.como_dict() for c in corridas],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGuardado en {ruta.relative_to(RAIZ)}")

    sys.exit(0 if resumen["tasa_paso_global"] == 1 else 1)


if __name__ == "__main__":
    main()
