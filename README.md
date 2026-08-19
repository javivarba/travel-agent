# Agente de viajes

Dado un lugar, un rango de fechas y una lista de intereses, devuelve
actividades y eventos reales para hacer en la zona — con costo aproximado,
traslado, horario y advertencias cuando corresponde. Nada de "los 5 mejores
lugares para visitar en X", relleno genérico o lugares inventados: cada
resultado sale de una búsqueda web real hecha por el modelo.

## Qué lo distingue

Los LLM alucinan lugares, precios y horarios con total confianza. Este
agente no le pide al modelo que "no invente" y confía en su palabra — verifica.

Cada resultado trae una `fuente_url`. Antes de devolver esa URL al usuario,
el backend la compara contra el registro de páginas que la API *efectivamente
consultó* durante la búsqueda (los bloques `web_search_tool_result` de la
respuesta), no contra lo que el modelo *dice* haber consultado. Todo ítem
cuya fuente no esté en ese registro se descarta antes de llegar a la salida
final, y queda contabilizado en una métrica (`items_descartados_por_fuente`)
que se usa para medir la calidad de cada versión del prompt.

Esa es la garantía central del proyecto: si un lugar aparece en la
respuesta, hay una página real, consultada en esa misma llamada, que lo
respalda.

Otras reglas de producto, no negociables: nunca recomienda alojamiento, y
nunca hardcodea la fecha — se inyecta en cada corrida.

## Estado del proyecto

En desarrollo activo. Lo que ya funciona:

- El contrato de datos (`app/models.py`, Pydantic) y la capa de agente
  (`app/agent.py`): llamadas a la API de Claude con la tool de búsqueda web,
  verificación de fuentes, extracción de métricas.
- El harness de evals (`evals/`): 8 casos dorados, aserciones automáticas y
  un juez con Claude para lo que las aserciones no capturan.

Lo que todavía no existe: el backend Flask (endpoints, jobs en background,
caché) y el frontend React descriptos en `docs/plan_agente_viajes_v2.md`.
Ese documento es la referencia de diseño completa del proyecto — ante
cualquier duda sobre por qué algo está hecho de una forma, la respuesta está
ahí.

## Instalación

Requiere Python 3.11+.

```bash
git clone https://github.com/javivarba/travel-agent.git
cd travel-agent
python -m venv .venv

# activar el entorno virtual
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows (cmd o PowerShell)

pip install -r requirements.txt
```

Después, creá un archivo `.env` en la raíz del repo con tu clave de la API
de Anthropic:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` está en `.gitignore` — nunca se commitea.

## Cómo correr

```bash
pytest                                     # tests unitarios: no llaman a la API
python -m evals.runner --fixtures          # harness de evals offline, contra fixtures grabados
python -m evals.runner --version v1 --n 3  # corrida real: consume API, cuesta centavos
```

El harness de evals tiene su propia guía en [README_evals.md](README_evals.md):
qué mide cada métrica, cómo grabar fixtures nuevos y cómo comparar versiones
de un prompt antes de promoverlo.

## Estructura

```
app/          # Contrato de datos y llamadas a la API
prompts/      # System prompts, versionados como archivos
evals/        # Casos dorados, aserciones y runner del harness
tests/        # Tests unitarios (contra fixtures, sin red)
docs/         # Plan de diseño, decisiones tomadas, instrucciones del proyecto
```

Ver [CLAUDE.md](CLAUDE.md) para las convenciones y reglas no negociables del
código.
