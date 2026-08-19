"""Claude como juez, para lo que las aserciones no alcanzan.

Las aserciones dicen si la respuesta es *correcta*. No dicen si es *buena*:
ocho museos obvios de Madrid pasan todas las validaciones y son una
recomendación mediocre. Eso es lo que mide esta rúbrica.

Acá sí se fuerza tool_choice: no hay búsqueda web de por medio, así que
forzar la entrega garantiza salida estructurada en una sola llamada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.models import RespuestaInvestigacion, esquema_para_tool
from evals.casos import Caso

MODELO_JUEZ = "claude-sonnet-5"

RUBRICA = """Sos un evaluador de sistemas de recomendación de viajes. Vas a
calificar la salida de un agente, no a mejorarla. Sé exigente: un 5 es
excepcional, un 3 es aceptable, y la mayoría de las salidas decentes caen
en 3.

Criterios, cada uno de 1 a 5:

1. relevancia — ¿las actividades responden a los intereses declarados, o
   son relleno genérico que aparecería para cualquier intereses?
2. variedad — ¿hay diversidad real de tipo, costo, duración y zona, o son
   ocho versiones de lo mismo?
3. accionabilidad — con esto en la mano, ¿se puede salir mañana? Traslado,
   costo, reserva, horario: ¿está lo necesario o hay que googlear todo de
   nuevo?

Penalizá lo obvio: para una capital, listar solo los tres museos que
aparecen en cualquier guía es baja relevancia aunque sea correcto.
Premiá el reporte honesto de ausencias: una zona pequeña con tres
resultados sólidos y categorías declaradas sin resultados vale más que
ocho ítems mediocres.

Entregá la calificación llamando a la herramienta."""


class Calificacion(BaseModel):
    relevancia: int = Field(ge=1, le=5)
    variedad: int = Field(ge=1, le=5)
    accionabilidad: int = Field(ge=1, le=5)
    justificacion_relevancia: str = Field(max_length=200)
    justificacion_variedad: str = Field(max_length=200)
    justificacion_accionabilidad: str = Field(max_length=200)
    mayor_debilidad: str = Field(max_length=300, description="El fallo más grave, en una frase.")

    @property
    def promedio(self) -> float:
        return round((self.relevancia + self.variedad + self.accionabilidad) / 3, 2)


@dataclass
class ResultadoJuez:
    ok: bool
    calificacion: Calificacion | None = None
    error: str | None = None

    def como_dict(self) -> dict:
        if not self.calificacion:
            return {"ok": False, "error": self.error}
        return {"ok": True, "promedio": self.calificacion.promedio,
                **self.calificacion.model_dump()}


def _compactar(r: RespuestaInvestigacion) -> dict:
    """Se le pasa al juez solo lo que necesita para juzgar. Mandarle el
    objeto completo gasta tokens y lo distrae con campos irrelevantes."""
    def act(a):
        return {
            "nombre": a.nombre,
            "categorias": [c.value for c in a.categorias],
            "descripcion": a.descripcion,
            "duracion": a.duracion_estimada,
            "costo": f"{a.costo_aproximado} {a.moneda}",
            "traslado": a.traslado,
            "reserva": a.requiere_reserva,
            "horario": a.horario,
            "advertencias": a.advertencias,
        }
    return {
        "nota_temporada": r.nota_temporada,
        "imprescindibles": [act(a) for a in r.imprescindibles],
        "segun_intereses": [act(a) for a in r.segun_intereses],
        "sin_resultados": [
            {"categoria": x.categoria.value, "nota": x.nota}
            for x in r.categorias_sin_resultados
        ],
    }


def juzgar(
    cliente: anthropic.Anthropic, caso: Caso, r: RespuestaInvestigacion
) -> ResultadoJuez:
    contexto = (
        f"Destino: {caso.lugar}\n"
        f"Fechas: {caso.fecha_inicio} a {caso.fecha_fin} ({caso.dias} días)\n"
        f"Intereses: {', '.join(c.value for c in caso.intereses) or '(ninguno)'}\n\n"
        f"Salida del agente:\n{json.dumps(_compactar(r), ensure_ascii=False, indent=2)}"
    )

    try:
        response = cliente.messages.create(
            model=MODELO_JUEZ,
            max_tokens=1500,
            system=[{"type": "text", "text": RUBRICA,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": contexto}],
            tools=[{
                "name": "calificar",
                "description": "Entrega la calificación según la rúbrica.",
                "input_schema": esquema_para_tool(Calificacion),
            }],
            tool_choice={"type": "tool", "name": "calificar"},
        )
    except anthropic.APIError as e:
        return ResultadoJuez(ok=False, error=f"API: {e}")

    for bloque in response.content:
        if getattr(bloque, "type", None) == "tool_use":
            try:
                return ResultadoJuez(ok=True, calificacion=Calificacion.model_validate(bloque.input))
            except ValidationError as e:
                return ResultadoJuez(ok=False, error=f"Calificación inválida: {e}")
    return ResultadoJuez(ok=False, error="El juez no llamó a la tool")
