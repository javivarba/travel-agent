"""Tests de las aserciones.

Una aserción que nunca se probó contra un caso que debería fallar no es una
aserción, es decoración. Estos tests construyen respuestas rotas a propósito
y verifican que el harness las detecte.

No tocan la API.
"""

from datetime import date

import pytest

from app.models import (
    Actividad,
    Categoria as C,
    CategoriaSinResultados,
    Evento,
    NivelFisico,
    RespuestaEventos,
    RespuestaInvestigacion,
)
from evals import aserciones
from evals.casos import Caso

URL = "https://ejemplo.cr/actividad"
URLS = {"ejemplo.cr/actividad"}


def actividad(nombre="Sendero Gandoca", categorias=(C.naturaleza,), **kw) -> Actividad:
    base = dict(
        nombre=nombre, categorias=list(categorias),
        descripcion="Caminata por el refugio.", duracion_estimada="2 horas",
        costo_aproximado="10", moneda="USD", traslado="15 min en carro",
        maps_query=f"{nombre}, Limón", requiere_reserva=False,
        nivel_fisico=NivelFisico.medio, advertencias=[], fuente_url=URL,
    )
    return Actividad(**{**base, **kw})


def caso(**kw) -> Caso:
    base = dict(
        id="test", lugar="Manzanillo, Costa Rica",
        fecha_inicio=date(2026, 9, 5), fecha_fin=date(2026, 9, 8),
        intereses=[C.naturaleza], prueba="test",
    )
    return Caso(**{**base, **kw})


def respuesta(**kw) -> RespuestaInvestigacion:
    base = dict(
        nota_temporada="Septiembre suele ser seco en el Caribe.",
        imprescindibles=[], segun_intereses=[], categorias_sin_resultados=[],
    )
    return RespuestaInvestigacion(**{**base, **kw})


def por_nombre(resultados, nombre):
    return next(r for r in resultados if r.nombre == nombre)


# --------------------------------------------------------------------------

def test_respuesta_limpia_pasa_todo_lo_bloqueante():
    r = respuesta(imprescindibles=[actividad("Playa Manzanillo", (C.playa_relax,))],
                  segun_intereses=[actividad()])
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert aserciones.resumen(res)["paso"]


def test_detecta_alojamiento_en_el_nombre():
    r = respuesta(imprescindibles=[actividad("Hotel Congo Bongo")])
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert not por_nombre(res, "sin_alojamiento_en_nombre").paso


def test_alojamiento_en_descripcion_es_solo_advertencia():
    """Un restaurante dentro de un hotel es legítimo. Bloquearlo sería un
    falso positivo, ignorarlo sería un hueco: por eso, advertencia."""
    r = respuesta(
        imprescindibles=[
            actividad("Restaurante Koki Beach", descripcion="Está dentro del Hotel X.")
        ],
        segun_intereses=[actividad()],  # cubre la categoría pedida
    )
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    a = por_nombre(res, "sin_alojamiento_en_descripcion")
    assert not a.paso and a.severidad is aserciones.Severidad.advertencia
    assert aserciones.resumen(res)["paso"]  # no bloquea


def test_detecta_exceso_por_seccion_en_viaje_de_un_dia():
    c = caso(fecha_fin=date(2026, 9, 5))  # 1 día -> máximo 3
    r = respuesta(imprescindibles=[actividad(f"Lugar {i}") for i in range(4)])
    res = aserciones.evaluar_investigacion(c, r, URLS)
    assert not por_nombre(res, "tope_por_seccion").paso


def test_detecta_fuente_fuera_del_set_de_busquedas():
    r = respuesta(imprescindibles=[actividad(fuente_url="https://inventado.cr/tour")])
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert not por_nombre(res, "fuentes_verificadas").paso


def test_normalizacion_de_url_tolera_www_y_query():
    r = respuesta(imprescindibles=[
        actividad(fuente_url="https://www.ejemplo.cr/actividad/?utm_source=x")
    ])
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert por_nombre(res, "fuentes_verificadas").paso


def test_detecta_duplicado_entre_secciones():
    r = respuesta(imprescindibles=[actividad("Playa Punta Uva", (C.playa_relax,))],
                  segun_intereses=[actividad("playa punta uva", (C.naturaleza,))])
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert not por_nombre(res, "sin_duplicados_entre_secciones").paso


def test_categoria_cubierta_solo_en_imprescindibles_pasa_cobertura():
    """Un ítem que califica para las dos secciones va solo a imprescindibles
    (regla del prompt). Eso no es ignorar la categoría: cobertura_de_categorias
    tiene que mirar ambas secciones, no solo segun_intereses."""
    c = caso(intereses=[C.naturaleza, C.playa_relax])
    r = respuesta(
        imprescindibles=[actividad("Refugio Gandoca", (C.naturaleza,))],
        segun_intereses=[actividad("Playa Manzanillo", (C.playa_relax,))],
    )
    res = aserciones.evaluar_investigacion(c, r, URLS)
    assert por_nombre(res, "cobertura_de_categorias").paso
    assert aserciones.resumen(res)["paso"]


def test_categoria_solo_en_imprescindibles_no_dispara_categoria_no_pedida():
    """imprescindibles es independiente de los intereses declarados: puede
    traer categorías fuera de lo pedido sin que sea una intrusión. Esa regla
    aplica solo a segun_intereses."""
    c = caso(intereses=[C.gastronomia])
    r = respuesta(
        imprescindibles=[actividad("Parque Central", (C.naturaleza,))],
        segun_intereses=[actividad("Restaurante", (C.gastronomia,))],
    )
    res = aserciones.evaluar_investigacion(c, r, URLS)
    assert por_nombre(res, "sin_categorias_no_pedidas").paso


def test_detecta_categoria_ignorada_en_silencio():
    """El fallo más sutil: pedís pesca, el modelo no la menciona ni con
    resultados ni como vacía, y la respuesta se ve bien."""
    c = caso(intereses=[C.naturaleza, C.pesca])
    r = respuesta(segun_intereses=[actividad()])
    res = aserciones.evaluar_investigacion(c, r, URLS)
    a = por_nombre(res, "cobertura_de_categorias")
    assert not a.paso and "pesca" in a.detalle


def test_detecta_contradiccion_con_resultados_y_declarada_vacia():
    r = respuesta(
        segun_intereses=[actividad()],
        categorias_sin_resultados=[CategoriaSinResultados(categoria=C.naturaleza, nota="no hay")],
    )
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert not por_nombre(res, "sin_contradiccion_vacio_lleno").paso


def test_detecta_categoria_no_pedida():
    r = respuesta(segun_intereses=[actividad(categorias=(C.vida_nocturna,))])
    res = aserciones.evaluar_investigacion(caso(), r, URLS)
    assert not por_nombre(res, "sin_categorias_no_pedidas").paso


def test_sin_intereses_exige_seccion_vacia():
    c = caso(intereses=[])
    r = respuesta(imprescindibles=[actividad()], segun_intereses=[actividad("Otro")])
    res = aserciones.evaluar_investigacion(c, r, URLS)
    assert not por_nombre(res, "segun_intereses_vacio_si_no_hay_intereses").paso


def test_exige_advertencia_o_declaracion_vacia_en_pesca():
    c = caso(intereses=[C.pesca], exige_advertencia_en=[C.pesca])
    sin_adv = respuesta(segun_intereses=[actividad("Tour de pesca", (C.pesca,))])
    assert not por_nombre(
        aserciones.evaluar_investigacion(c, sin_adv, URLS), "advertencia_o_vacio_pesca").paso

    con_adv = respuesta(segun_intereses=[
        actividad("Tour de pesca", (C.pesca,),
                  advertencias=["Restricciones en el Refugio Gandoca-Manzanillo"])
    ])
    assert por_nombre(
        aserciones.evaluar_investigacion(c, con_adv, URLS), "advertencia_o_vacio_pesca").paso


def test_trampa_climatica_dispara_advertencia():
    c = caso(veto_nota_temporada=["temporada alta de lluvia"])
    r = respuesta(nota_temporada="Septiembre es temporada alta de lluvia en la zona.")
    res = aserciones.evaluar_investigacion(c, r, URLS)
    a = por_nombre(res, "nota_temporada_sin_frases_vetadas")
    assert not a.paso and a.severidad is aserciones.Severidad.advertencia


def test_veto_climatico_ignora_tildes_y_mayusculas():
    c = caso(veto_nota_temporada=["pico de lluvias"])
    r = respuesta(nota_temporada="Es el PICO DE LLUVIAS del año.")
    res = aserciones.evaluar_investigacion(c, r, URLS)
    assert not por_nombre(res, "nota_temporada_sin_frases_vetadas").paso


# --------------------------------------------------------------------------
# Eventos
# --------------------------------------------------------------------------

def evento(nombre="Concierto", fecha_hora="2026-09-06T20:00", **kw) -> Evento:
    base = dict(
        nombre=nombre, tipo="concierto", fecha_hora=fecha_hora,
        lugar_especifico="Plaza central", maps_query="Plaza central, Manzanillo",
        requiere_boleto=True, costo_aproximado="20", moneda="USD",
        donde_comprar="sitio oficial", fuente_url=URL,
    )
    return Evento(**{**base, **kw})


def test_detecta_evento_fuera_del_rango():
    c = caso(intereses=[C.eventos_deportivos_culturales])
    r = RespuestaEventos(eventos=[evento(fecha_hora="2026-10-01T20:00")])
    res = aserciones.evaluar_eventos(c, r, URLS)
    assert not por_nombre(res, "eventos_dentro_del_rango").paso


@pytest.mark.parametrize("fecha", ["2026-09-06T20:00", "2026-09-06 20:00", "2026-09-06"])
def test_acepta_formatos_de_fecha_razonables(fecha):
    c = caso(intereses=[C.eventos_deportivos_culturales])
    res = aserciones.evaluar_eventos(c, RespuestaEventos(eventos=[evento(fecha_hora=fecha)]), URLS)
    assert por_nombre(res, "fecha_hora_parseable").paso
    assert por_nombre(res, "eventos_dentro_del_rango").paso


def test_lista_vacia_debe_estar_declarada():
    c = caso(intereses=[C.eventos_deportivos_culturales])
    res = aserciones.evaluar_eventos(c, RespuestaEventos(eventos=[]), URLS)
    assert not por_nombre(res, "vacio_declarado").paso

    r = RespuestaEventos(eventos=[], categorias_sin_resultados=[
        CategoriaSinResultados(categoria=C.eventos_deportivos_culturales,
                               nota="Sin eventos programados para esas fechas.")])
    assert por_nombre(aserciones.evaluar_eventos(c, r, URLS), "vacio_declarado").paso


def test_no_debe_haber_eventos_si_no_se_pidieron():
    res = aserciones.evaluar_eventos(caso(), RespuestaEventos(eventos=[evento()]), URLS)
    assert not por_nombre(res, "sin_eventos_si_no_se_pidieron").paso
