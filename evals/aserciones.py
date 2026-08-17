"""Aserciones automáticas.

Separadas del runner a propósito: son funciones puras sobre datos ya
parseados, así que se testean con pytest sin tocar la API.

Severidad:
  BLOQUEANTE — el prompt está mal, no se promueve la versión
  ADVERTENCIA — posible falso positivo, requiere ojo humano
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from app.agent import normalizar_url
from app.models import Actividad, Categoria, RespuestaEventos, RespuestaInvestigacion
from evals.casos import Caso


class Severidad(str, Enum):
    bloqueante = "bloqueante"
    advertencia = "advertencia"


@dataclass
class Resultado:
    nombre: str
    paso: bool
    severidad: Severidad = Severidad.bloqueante
    detalle: str = ""

    def como_dict(self) -> dict:
        return {"nombre": self.nombre, "paso": self.paso,
                "severidad": self.severidad.value, "detalle": self.detalle}


# --------------------------------------------------------------------------

LEXICO_ALOJAMIENTO = [
    "hotel", "hostal", "hostel", "airbnb", "alojamiento", "hospedaje",
    "lodge", "resort", "camping", "cabinas", "posada", "apartahotel",
    "bed and breakfast", "b&b", "glamping",
]


def _plano(texto: str) -> str:
    """Minúsculas sin tildes, para que 'Alojamiento' y 'alojamiénto' colisionen."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _menciona_alojamiento(texto: str) -> list[str]:
    plano = _plano(texto)
    return [p for p in LEXICO_ALOJAMIENTO if re.search(rf"\b{re.escape(p)}\b", plano)]


def _actividades(r: RespuestaInvestigacion) -> list[Actividad]:
    return [*r.imprescindibles, *r.segun_intereses]


def _parsear_fecha_evento(valor: str) -> date | None:
    limpio = valor.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(limpio).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(limpio[:len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Investigación
# --------------------------------------------------------------------------

def evaluar_investigacion(
    caso: Caso, r: RespuestaInvestigacion, urls_consultadas: set[str]
) -> list[Resultado]:
    out: list[Resultado] = []
    actividades = _actividades(r)

    # --- Alojamiento -------------------------------------------------------
    # En el nombre es violación dura. En la descripción puede ser legítimo
    # ("el restaurante está dentro del Hotel X"), así que va como advertencia.
    en_nombre = {a.nombre: _menciona_alojamiento(a.nombre) for a in actividades}
    culpables = {n: p for n, p in en_nombre.items() if p}
    out.append(Resultado(
        "sin_alojamiento_en_nombre", not culpables,
        detalle="" if not culpables else f"{culpables}",
    ))

    en_desc = {
        a.nombre: _menciona_alojamiento(a.descripcion)
        for a in actividades if _menciona_alojamiento(a.descripcion)
    }
    out.append(Resultado(
        "sin_alojamiento_en_descripcion", not en_desc, Severidad.advertencia,
        detalle="" if not en_desc else f"revisar a mano: {en_desc}",
    ))

    # --- Tope por sección --------------------------------------------------
    excesos = {
        s: len(v) for s, v in
        {"imprescindibles": r.imprescindibles, "segun_intereses": r.segun_intereses}.items()
        if len(v) > caso.max_resultados
    }
    out.append(Resultado(
        "tope_por_seccion", not excesos,
        detalle="" if not excesos else f"máximo {caso.max_resultados}, obtenido {excesos}",
    ))

    # --- Fuentes verificables ---------------------------------------------
    # El filtro de agent.py ya descarta las no verificables; si algo llega
    # hasta acá sin verificar, el filtro está roto.
    sin_fuente = [
        a.nombre for a in actividades
        if normalizar_url(str(a.fuente_url)) not in urls_consultadas
    ] if urls_consultadas else []
    out.append(Resultado(
        "fuentes_verificadas", not sin_fuente,
        detalle="" if not sin_fuente else f"fuera del set de búsquedas: {sin_fuente}",
    ))

    # --- Duplicados entre secciones ---------------------------------------
    nombres_i = {_plano(a.nombre) for a in r.imprescindibles}
    nombres_s = {_plano(a.nombre) for a in r.segun_intereses}
    dupes = nombres_i & nombres_s
    out.append(Resultado(
        "sin_duplicados_entre_secciones", not dupes,
        detalle="" if not dupes else f"{sorted(dupes)}",
    ))

    # --- Cobertura de categorías ------------------------------------------
    # Toda categoría pedida aparece con resultados o declarada sin ellos.
    # Sin esto el modelo puede ignorar una categoría en silencio.
    # Mira ambas secciones: un ítem que califica para imprescindibles y
    # segun_intereses va solo a imprescindibles (regla del prompt), así que
    # limitarse a segun_intereses da falsos positivos en categorías cubiertas
    # ahí.
    pedidas = {c for c in caso.intereses if c != Categoria.eventos_deportivos_culturales}
    con_resultados = {c for a in _actividades(r) for c in a.categorias}
    declaradas = {x.categoria for x in r.categorias_sin_resultados}
    huerfanas = pedidas - con_resultados - declaradas
    out.append(Resultado(
        "cobertura_de_categorias", not huerfanas,
        detalle="" if not huerfanas else f"ignoradas en silencio: {sorted(c.value for c in huerfanas)}",
    ))

    # --- Coherencia --------------------------------------------------------
    contradictorias = con_resultados & declaradas
    out.append(Resultado(
        "sin_contradiccion_vacio_lleno", not contradictorias,
        detalle="" if not contradictorias else f"con resultados y declaradas vacías: {contradictorias}",
    ))

    # Alcance distinto a con_resultados a propósito: imprescindibles es
    # independiente de los intereses declarados, así que puede traer
    # cualquier categoría sin que sea una intrusión. Esta aserción es sobre
    # segun_intereses específicamente: ahí sí toda categoría tiene que
    # corresponder a un interés pedido.
    intrusas = {c for a in r.segun_intereses for c in a.categorias} - set(caso.intereses)
    out.append(Resultado(
        "sin_categorias_no_pedidas", not intrusas,
        detalle="" if not intrusas else f"{sorted(c.value for c in intrusas)}",
    ))

    # --- Sin intereses -----------------------------------------------------
    if not caso.intereses:
        out.append(Resultado(
            "segun_intereses_vacio_si_no_hay_intereses",
            not r.segun_intereses,
            detalle=f"{len(r.segun_intereses)} ítems sin intereses declarados",
        ))
        out.append(Resultado(
            "imprescindibles_poblado", bool(r.imprescindibles),
            detalle="imprescindibles vacío sin motivo",
        ))

    # --- Accionabilidad ----------------------------------------------------
    sin_maps = [a.nombre for a in actividades if not a.maps_query.strip()]
    out.append(Resultado(
        "maps_query_presente", not sin_maps,
        detalle="" if not sin_maps else f"{sin_maps}",
    ))

    # --- Advertencias esperadas -------------------------------------------
    for cat in caso.exige_advertencia_en:
        relevantes = [a for a in r.segun_intereses if cat in a.categorias]
        if not relevantes:
            out.append(Resultado(
                f"advertencia_o_vacio_{cat.value}",
                cat in declaradas,
                detalle=f"sin resultados de {cat.value} pero tampoco declarada vacía",
            ))
        else:
            con_adv = [a for a in relevantes if a.advertencias]
            out.append(Resultado(
                f"advertencia_o_vacio_{cat.value}", bool(con_adv),
                detalle=f"{len(relevantes)} ítems de {cat.value}, ninguno con advertencias",
            ))

    # --- Trampa semántica en nota_temporada -------------------------------
    if caso.veto_nota_temporada:
        nota = _plano(r.nota_temporada)
        hits = [f for f in caso.veto_nota_temporada if _plano(f) in nota]
        out.append(Resultado(
            "nota_temporada_sin_frases_vetadas", not hits, Severidad.advertencia,
            detalle="" if not hits else f"frases sospechosas {hits} — revisar: {r.nota_temporada!r}",
        ))

    out.append(Resultado(
        "nota_temporada_no_vacia", bool(r.nota_temporada.strip()), Severidad.advertencia,
    ))

    return out


# --------------------------------------------------------------------------
# Eventos
# --------------------------------------------------------------------------

def evaluar_eventos(
    caso: Caso, r: RespuestaEventos, urls_consultadas: set[str]
) -> list[Resultado]:
    out: list[Resultado] = []

    if not caso.pide_eventos:
        out.append(Resultado(
            "sin_eventos_si_no_se_pidieron", not r.eventos,
            detalle=f"{len(r.eventos)} eventos sin haberse pedido la categoría",
        ))
        return out

    fuera, ilegibles = [], []
    for e in r.eventos:
        f = _parsear_fecha_evento(e.fecha_hora)
        if f is None:
            ilegibles.append((e.nombre, e.fecha_hora))
        elif not (caso.fecha_inicio <= f <= caso.fecha_fin):
            fuera.append((e.nombre, e.fecha_hora))

    out.append(Resultado(
        "eventos_dentro_del_rango", not fuera,
        detalle="" if not fuera else f"{fuera}",
    ))
    out.append(Resultado(
        "fecha_hora_parseable", not ilegibles,
        detalle="" if not ilegibles else f"{ilegibles}",
    ))
    out.append(Resultado(
        "tope_de_eventos", len(r.eventos) <= 15,
        detalle=f"{len(r.eventos)} eventos",
    ))

    sin_fuente = [
        e.nombre for e in r.eventos
        if normalizar_url(str(e.fuente_url)) not in urls_consultadas
    ] if urls_consultadas else []
    out.append(Resultado(
        "fuentes_verificadas_eventos", not sin_fuente,
        detalle="" if not sin_fuente else f"{sin_fuente}",
    ))

    # Cero eventos es un resultado válido, pero tiene que estar declarado.
    if not r.eventos:
        declaradas = {x.categoria for x in r.categorias_sin_resultados}
        out.append(Resultado(
            "vacio_declarado",
            Categoria.eventos_deportivos_culturales in declaradas,
            detalle="lista vacía sin nota en categorias_sin_resultados",
        ))

    con_boleto_sin_donde = [
        e.nombre for e in r.eventos if e.requiere_boleto and not e.donde_comprar.strip()
    ]
    out.append(Resultado(
        "boleteria_accionable", not con_boleto_sin_donde, Severidad.advertencia,
        detalle="" if not con_boleto_sin_donde else f"{con_boleto_sin_donde}",
    ))

    return out


def resumen(resultados: list[Resultado]) -> dict:
    bloq = [r for r in resultados if r.severidad is Severidad.bloqueante]
    return {
        "total": len(resultados),
        "bloqueantes_fallidas": sum(1 for r in bloq if not r.paso),
        "advertencias": sum(
            1 for r in resultados
            if r.severidad is Severidad.advertencia and not r.paso
        ),
        "paso": all(r.paso for r in bloq),
    }
