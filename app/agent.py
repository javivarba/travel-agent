"""Llamadas al modelo y verificación anti-alucinación.

Interfaz que consume el harness de evals:
    investigar(...) -> ResultadoAgente[RespuestaInvestigacion]
    buscar_eventos(...) -> ResultadoAgente[RespuestaEventos]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Generic, TypeVar
from urllib.parse import urlparse

import anthropic
from pydantic import BaseModel, ValidationError

from app.models import (
    Categoria,
    RespuestaEventos,
    RespuestaInvestigacion,
    esquema_para_tool,
)

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
PROMPTS = RAIZ / "prompts"

MODELO_INVESTIGACION = "claude-sonnet-5"
TOOL_BUSQUEDA = "web_search_20260318"
COSTO_POR_BUSQUEDA_USD = 0.01

T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------

@dataclass
class Metricas:
    busquedas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    tokens_cache_lectura: int = 0
    items_descartados_por_fuente: int = 0
    items_totales: int = 0

    @property
    def costo_busqueda_usd(self) -> float:
        return self.busquedas * COSTO_POR_BUSQUEDA_USD

    @property
    def tasa_descarte(self) -> float:
        """Indicador principal de calidad del prompt. Si sube entre
        versiones, la versión nueva es peor. No es opinión."""
        return self.items_descartados_por_fuente / self.items_totales if self.items_totales else 0.0

    def como_dict(self) -> dict:
        return {
            **self.__dict__,
            "costo_busqueda_usd": round(self.costo_busqueda_usd, 4),
            "tasa_descarte": round(self.tasa_descarte, 4),
        }


@dataclass
class ResultadoAgente(Generic[T]):
    ok: bool
    respuesta: T | None = None
    error: str | None = None
    urls_consultadas: set[str] = field(default_factory=set)
    metricas: Metricas = field(default_factory=Metricas)
    crudo: dict | None = None  # payload del tool_use, para grabar fixtures


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def normalizar_url(url: str) -> str:
    """Compara URLs ignorando esquema, www, query y fragmento.

    Sin esto, la verificación falla por diferencias cosméticas: el modelo
    devuelve la URL canónica y el resultado de búsqueda trae parámetros de
    tracking, o al revés.
    """
    try:
        p = urlparse(str(url))
    except ValueError:
        return str(url).strip().lower()
    host = (p.netloc or "").lower().removeprefix("www.")
    camino = (p.path or "/").rstrip("/") or "/"
    return f"{host}{camino}"


def _atributo(bloque: Any, nombre: str, defecto=None):
    """Los bloques llegan como objetos del SDK o como dicts (fixtures)."""
    if isinstance(bloque, dict):
        return bloque.get(nombre, defecto)
    return getattr(bloque, nombre, defecto)


def extraer_urls_consultadas(response: Any) -> set[str]:
    """URLs que la API efectivamente buscó, desde los bloques
    web_search_tool_result. Es el conjunto contra el que se valida
    cualquier fuente_url que devuelva el modelo."""
    urls: set[str] = set()
    for bloque in _atributo(response, "content", []) or []:
        if _atributo(bloque, "type") != "web_search_tool_result":
            continue
        contenido = _atributo(bloque, "content", []) or []
        if isinstance(contenido, dict):  # bloque de error
            continue
        for resultado in contenido:
            url = _atributo(resultado, "url")
            if url:
                urls.add(normalizar_url(url))
    return urls


def extraer_entrega(response: Any, nombre_tool: str) -> dict | None:
    """Payload de la tool de entrega. Se toma el último tool_use con ese
    nombre: si el modelo corrige y vuelve a llamar, gana la corrección."""
    payload = None
    for bloque in _atributo(response, "content", []) or []:
        if _atributo(bloque, "type") == "tool_use" and _atributo(bloque, "name") == nombre_tool:
            payload = _atributo(bloque, "input")
    return payload


def contar_busquedas(response: Any) -> int:
    uso = _atributo(response, "usage")
    if uso is not None:
        servidor = _atributo(uso, "server_tool_use")
        if servidor is not None:
            return _atributo(servidor, "web_search_requests", 0) or 0
    return sum(
        1 for b in (_atributo(response, "content", []) or [])
        if _atributo(b, "type") == "web_search_tool_result"
    )


def _metricas_de_uso(response: Any) -> Metricas:
    uso = _atributo(response, "usage")
    return Metricas(
        busquedas=contar_busquedas(response),
        tokens_entrada=_atributo(uso, "input_tokens", 0) or 0,
        tokens_salida=_atributo(uso, "output_tokens", 0) or 0,
        tokens_cache_lectura=_atributo(uso, "cache_read_input_tokens", 0) or 0,
    )


# --------------------------------------------------------------------------
# Verificación de fuentes
# --------------------------------------------------------------------------

def filtrar_por_fuente(payload: dict, urls: set[str], metricas: Metricas) -> dict:
    """Descarta todo ítem cuya fuente_url no esté entre las URLs consultadas.

    Es la única defensa objetiva contra la invención de lugares: el modelo
    puede escribir cualquier URL, pero no puede falsificar el registro de
    búsquedas de la API.
    """
    if not urls:
        log.warning("Sin URLs consultadas; se omite la verificación de fuentes")
        return payload

    limpio = dict(payload)
    for seccion in ("imprescindibles", "segun_intereses", "eventos"):
        items = limpio.get(seccion)
        if not isinstance(items, list):
            continue
        conservados = []
        for item in items:
            metricas.items_totales += 1
            fuente = item.get("fuente_url") if isinstance(item, dict) else None
            if fuente and normalizar_url(fuente) in urls:
                conservados.append(item)
            else:
                metricas.items_descartados_por_fuente += 1
                log.info("Descartado por fuente no verificable: %s (%s)",
                         (item or {}).get("nombre"), fuente)
        limpio[seccion] = conservados
    return limpio


# --------------------------------------------------------------------------
# Llamadas
# --------------------------------------------------------------------------

def _llamar(
    *,
    cliente: anthropic.Anthropic,
    system_prompt: str,
    mensaje_usuario: str,
    modelo_respuesta: type[T],
    nombre_tool: str,
    descripcion_tool: str,
    max_busquedas: int,
    pais: str | None,
) -> ResultadoAgente[T]:
    tool_busqueda: dict = {
        "type": TOOL_BUSQUEDA,
        "name": "web_search",
        "max_uses": max_busquedas,
        # Default de la API es ["code_execution_20260120"]: las búsquedas
        # correrían dentro de code execution y los web_search_tool_result
        # llegarían anidados, no en el primer nivel de response.content.
        # extraer_urls_consultadas() los busca planos — con el default
        # devolvería un set vacío y se descartaría el 100% de los ítems.
        "allowed_callers": ["direct"],
    }
    if pais:
        tool_busqueda["user_location"] = {"type": "approximate", "country": pais}

    try:
        response = cliente.messages.create(
            model=MODELO_INVESTIGACION,
            max_tokens=8000,
            system=[{
                "type": "text",
                "text": system_prompt,
                # El prompt + schema son largos y estáticos: se repiten en
                # cada corrida de evals. Sin caché, se paga completo cada vez.
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": mensaje_usuario}],
            tools=[
                tool_busqueda,
                {
                    "name": nombre_tool,
                    "description": descripcion_tool,
                    "input_schema": esquema_para_tool(modelo_respuesta),
                },
            ],
            # tool_choice queda en automático a propósito: forzar la tool de
            # entrega haría que el modelo entregue sin haber buscado.
        )
    except anthropic.APIError as e:
        return ResultadoAgente(ok=False, error=f"API: {e}")

    metricas = _metricas_de_uso(response)
    urls = extraer_urls_consultadas(response)
    payload = extraer_entrega(response, nombre_tool)

    if payload is None:
        return ResultadoAgente(
            ok=False,
            error=f"El modelo no llamó a {nombre_tool} (stop_reason={_atributo(response, 'stop_reason')})",
            urls_consultadas=urls,
            metricas=metricas,
        )

    payload = filtrar_por_fuente(payload, urls, metricas)

    try:
        respuesta = modelo_respuesta.model_validate(payload)
    except ValidationError as e:
        return ResultadoAgente(
            ok=False,
            error=f"Schema inválido: {e.error_count()} errores — {e.errors()[:3]}",
            urls_consultadas=urls,
            metricas=metricas,
            crudo=payload,
        )

    return ResultadoAgente(
        ok=True, respuesta=respuesta, urls_consultadas=urls,
        metricas=metricas, crudo=payload,
    )


def investigar(
    *,
    cliente: anthropic.Anthropic,
    lugar: str,
    fecha_inicio: date,
    fecha_fin: date,
    intereses: list[Categoria],
    fecha_actual: date,
    version_prompt: str = "v1",
    pais: str | None = None,
) -> ResultadoAgente[RespuestaInvestigacion]:
    dias = (fecha_fin - fecha_inicio).days + 1
    max_resultados = min(8, dias * 3)
    system = (PROMPTS / f"investigacion_{version_prompt}.md").read_text(encoding="utf-8")
    system = system.format(
        fecha_actual=fecha_actual.isoformat(),
        lugar=lugar,
        fecha_inicio=fecha_inicio.isoformat(),
        fecha_fin=fecha_fin.isoformat(),
        dias=dias,
        intereses=", ".join(c.value for c in intereses) or "(ninguno)",
        max_resultados=max_resultados,
    )
    return _llamar(
        cliente=cliente,
        system_prompt=system,
        mensaje_usuario=f"Investigá actividades en {lugar} para el viaje indicado.",
        modelo_respuesta=RespuestaInvestigacion,
        nombre_tool="entregar_investigacion",
        descripcion_tool="Entrega el resultado final de la investigación de actividades.",
        max_busquedas=10,
        pais=pais,
    )


def buscar_eventos(
    *,
    cliente: anthropic.Anthropic,
    lugar: str,
    fecha_inicio: date,
    fecha_fin: date,
    fecha_actual: date,
    version_prompt: str = "v1",
    pais: str | None = None,
) -> ResultadoAgente[RespuestaEventos]:
    system = (PROMPTS / f"eventos_{version_prompt}.md").read_text(encoding="utf-8")
    system = system.format(
        fecha_actual=fecha_actual.isoformat(),
        lugar=lugar,
        fecha_inicio=fecha_inicio.isoformat(),
        fecha_fin=fecha_fin.isoformat(),
    )
    return _llamar(
        cliente=cliente,
        system_prompt=system,
        mensaje_usuario=f"Buscá eventos en {lugar} entre {fecha_inicio} y {fecha_fin}.",
        modelo_respuesta=RespuestaEventos,
        nombre_tool="entregar_eventos",
        descripcion_tool="Entrega la lista final de eventos confirmados.",
        max_busquedas=6,
        pais=pais,
    )
