"""Fuente única de verdad del contrato de datos.

De acá salen: el input_schema de las tools de entrega, la validación de las
respuestas del modelo y (vía generación) los tipos del frontend.
Nunca escribir un schema JSON a mano en otro lugar.
"""

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Categoria(str, Enum):
    aventura_deportes = "aventura_deportes"
    naturaleza = "naturaleza"
    cultura_historia = "cultura_historia"
    gastronomia = "gastronomia"
    playa_relax = "playa_relax"
    vida_nocturna = "vida_nocturna"
    fotografia_paisajes = "fotografia_paisajes"
    compras_artesania = "compras_artesania"
    eventos_deportivos_culturales = "eventos_deportivos_culturales"
    pesca = "pesca"


class NivelFisico(str, Enum):
    bajo = "bajo"
    medio = "medio"
    alto = "alto"


class Actividad(BaseModel):
    nombre: str
    categorias: list[Categoria] = Field(min_length=1)
    descripcion: str
    duracion_estimada: str
    costo_aproximado: str
    moneda: str
    traslado: str
    maps_query: str
    requiere_reserva: bool
    horario: str | None = None
    nivel_fisico: NivelFisico
    advertencias: list[str] = []
    fuente_url: HttpUrl


class Evento(BaseModel):
    nombre: str
    tipo: Literal["deportivo", "cultural", "concierto", "exhibicion", "festival", "otro"]
    fecha_hora: str  # ISO 8601, hora local del destino
    lugar_especifico: str
    maps_query: str
    requiere_boleto: bool
    costo_aproximado: str
    moneda: str
    donde_comprar: str
    fuente_url: HttpUrl


class CategoriaSinResultados(BaseModel):
    categoria: Categoria
    nota: str


class RespuestaInvestigacion(BaseModel):
    nota_temporada: str
    imprescindibles: list[Actividad] = Field(max_length=8)
    segun_intereses: list[Actividad] = Field(max_length=8)
    categorias_sin_resultados: list[CategoriaSinResultados] = []


class RespuestaEventos(BaseModel):
    eventos: list[Evento] = Field(max_length=15)
    categorias_sin_resultados: list[CategoriaSinResultados] = []


class Itinerario(BaseModel):
    lugar: str
    fecha_inicio: date
    fecha_fin: date
    generado_en: datetime
    nota_temporada: str
    imprescindibles: list[Actividad]
    segun_intereses: list[Actividad]
    eventos: list[Evento]
    categorias_sin_resultados: list[CategoriaSinResultados]


def esquema_para_tool(modelo: type[BaseModel]) -> dict:
    """input_schema para una tool de entrega.

    Pydantic emite `$defs` con `$ref` para los tipos anidados. La API los
    acepta, pero conviene pasar por acá para tener un único punto donde
    ajustar si algún día hay que aplanarlos.
    """
    return modelo.model_json_schema()
