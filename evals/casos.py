"""Casos dorados.

Cada caso aísla un modo de fallo distinto. Si agregás uno, escribí en
`prueba` qué falla se supone que detecta — un caso que no puede fallar por
una razón concreta es ruido que cuesta dinero en cada corrida.
"""

from dataclasses import dataclass, field
from datetime import date

from app.models import Categoria as C

TODAS = list(C)


@dataclass(frozen=True)
class Caso:
    id: str
    lugar: str
    fecha_inicio: date
    fecha_fin: date
    intereses: list[C]
    prueba: str
    pais: str | None = None
    espera_error: bool = False
    # Palabras que NO deberían aparecer en nota_temporada (trampas semánticas)
    veto_nota_temporada: list[str] = field(default_factory=list)
    # Categorías donde se espera advertencia legal/de riesgo en los ítems
    exige_advertencia_en: list[C] = field(default_factory=list)

    @property
    def dias(self) -> int:
        return (self.fecha_fin - self.fecha_inicio).days + 1

    @property
    def max_resultados(self) -> int:
        return min(8, self.dias * 3)

    @property
    def pide_eventos(self) -> bool:
        return C.eventos_deportivos_culturales in self.intereses


CASOS: list[Caso] = [
    Caso(
        id="01_manzanillo_cobertura_baja",
        lugar="Manzanillo, Limón, Costa Rica",
        fecha_inicio=date(2026, 9, 5),
        fecha_fin=date(2026, 9, 8),
        intereses=TODAS,
        pais="CR",
        prueba=(
            "Zona pequeña con poca cobertura web. Debe reportar categorías "
            "vacías en categorias_sin_resultados en vez de rellenar hasta el "
            "máximo. Es el caso que rompía el prompt v1 con su piso de 5–8."
        ),
    ),
    Caso(
        id="02_madrid_cobertura_alta",
        lugar="Madrid, España",
        fecha_inicio=date(2026, 11, 20),
        fecha_fin=date(2026, 11, 24),
        intereses=[C.cultura_historia, C.gastronomia],
        pais="ES",
        prueba=(
            "Cobertura sobrada. El riesgo acá no es alucinar sino volcar lo "
            "obvio sin curar: se mide con el juez, no con aserciones."
        ),
    ),
    Caso(
        id="03_madrid_un_dia",
        lugar="Madrid, España",
        fecha_inicio=date(2026, 11, 20),
        fecha_fin=date(2026, 11, 20),
        intereses=[C.cultura_historia],
        pais="ES",
        prueba="Escalado por duración: máximo 3 por sección, no 8.",
    ),
    Caso(
        id="04_madrid_tres_semanas",
        lugar="Madrid, España",
        fecha_inicio=date(2026, 11, 10),
        fecha_fin=date(2026, 11, 30),
        intereses=[C.cultura_historia, C.eventos_deportivos_culturales],
        pais="ES",
        prueba="Rango largo: tope de 15 eventos, sin explosión de tokens.",
    ),
    Caso(
        id="05_lugar_inexistente",
        lugar="Villa Ferniquiel de los Robles, Costa Rica",
        fecha_inicio=date(2026, 9, 5),
        fecha_fin=date(2026, 9, 8),
        intereses=[C.naturaleza, C.gastronomia],
        pais="CR",
        espera_error=True,
        prueba=(
            "El destino no existe. Debe fallar limpio o devolver todo vacío, "
            "nunca inventar un pueblo. La verificación de fuentes debería "
            "vaciar cualquier invención."
        ),
    ),
    Caso(
        id="06_puerto_viejo_solo_pesca",
        lugar="Puerto Viejo de Talamanca, Limón, Costa Rica",
        fecha_inicio=date(2026, 9, 5),
        fecha_fin=date(2026, 9, 8),
        intereses=[C.pesca],
        pais="CR",
        exige_advertencia_en=[C.pesca],
        prueba=(
            "Categoría de nicho con restricción legal real: el Refugio "
            "Gandoca-Manzanillo regula la pesca. O reporta sin resultados, o "
            "incluye la advertencia. Callarse la restricción es el fallo."
        ),
    ),
    Caso(
        id="07_madrid_sin_intereses",
        lugar="Madrid, España",
        fecha_inicio=date(2026, 11, 20),
        fecha_fin=date(2026, 11, 24),
        intereses=[],
        pais="ES",
        prueba=(
            "Sin intereses: segun_intereses debe quedar vacío y "
            "imprescindibles poblado. Verifica que no confunda las secciones."
        ),
    ),
    Caso(
        id="08_trampa_climatica_caribe",
        lugar="Manzanillo, Limón, Costa Rica",
        fecha_inicio=date(2026, 9, 5),
        fecha_fin=date(2026, 9, 12),
        intereses=[C.playa_relax, C.naturaleza],
        pais="CR",
        veto_nota_temporada=["temporada alta de lluvia", "lluvias intensas", "pico de lluvias"],
        prueba=(
            "Trampa semántica: septiembre–octubre es la ventana más seca del "
            "Caribe costarricense, al revés que el Pacífico. Un prompt sin la "
            "regla de microclimas afirma lo contrario con total confianza. "
            "El veto es heurístico — revisar la nota a mano cuando dispare."
        ),
    ),
]

POR_ID = {c.id: c for c in CASOS}
