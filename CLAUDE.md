# CLAUDE.md — Agente de viajes

Contexto para Claude Code al trabajar en este repo. Léelo antes de tocar código.

## Qué es esto

Agente que, dado un lugar, fechas e intereses, devuelve actividades reales y verificables para hacer en la zona. Backend Flask, frontend React, investigación vía API de Claude con la tool de búsqueda web.

El plan completo está en `docs/plan_agente_viajes_v2.md`. Ante cualquier duda de diseño, ese documento manda sobre lo que parezca razonable en el momento.

## Sobre quién escribe este código

Program Manager senior en formación fullstack. Ya construyó en producción: chatbot de WhatsApp (Flask + Postgres + Redis + Celery + Twilio) y un generador web con la API de Claude. Sabe Python, POO, testing, estructuras de datos, patrones de diseño, Flask, SQL y Postgres. React es territorio nuevo.

**Cómo ayudar mejor:**

- Explicá el *por qué* de una decisión técnica, no solo el *qué*. El objetivo del proyecto es aprender, no solo entregar.
- En Python, asumí nivel intermedio-alto: no expliques qué es un decorador. En React, explicá los conceptos la primera vez que aparezcan.
- Cuando haya dos formas de hacer algo, decí cuál elegirías y por qué, en vez de listar opciones sin recomendación.
- Si una instrucción del usuario contradice este archivo o el plan, decilo antes de implementarla.

## Reglas no negociables

1. **`app/models.py` es la única fuente de verdad del schema.** El `input_schema` de las tools sale de `model_json_schema()`. Nunca escribas un schema JSON a mano. Nunca dupliques la definición en el frontend sin generarla desde acá.

2. **No se toca el schema sin actualizar, en el mismo commit:** los modelos Pydantic, las aserciones de los evals y los fixtures afectados.

3. **`tool_choice` queda en automático** en las llamadas de investigación y eventos. Forzarlo a la tool de entrega impide que el modelo busque.

4. **Todo ítem devuelto debe traer `fuente_url`, y esa URL debe estar en el conjunto de URLs efectivamente consultadas** (bloques `web_search_tool_result`). Los ítems que no pasen esa verificación se descartan y se cuentan en la métrica `items_descartados_por_fuente`.

5. **`max_uses` y `max_tokens` siempre presentes** en toda llamada a la API. Sin techo de costo no se mergea.

6. **`cache_control: ephemeral` en el bloque system.** El prompt es largo y estático.

7. **Nunca recomendar alojamiento.** Es exclusión permanente de producto, no una limitación temporal. Si alguna vez parece útil agregarlo, la respuesta es no.

8. **Los prompts se versionan como archivos**, en `prompts/`. Editar un prompt = crear `_v{n+1}.md` y correr los evals. No se edita un archivo de prompt en sitio.

9. **Nunca hardcodees la fecha actual en un prompt.** Se inyecta desde el backend en tiempo de ejecución.

10. **Desarrollo contra fixtures.** Si estás iterando sobre parsing, frontend o formato, usá `tests/fixtures/*.json`. Llamadas reales solo cuando estés probando el prompt.

## Estructura

```
app/
  models.py          # Pydantic — fuente de verdad del contrato
  agent.py           # Llamadas a la API, tools, verificación de URLs
  routes.py          # Endpoints Flask
  jobs.py            # ThreadPoolExecutor + registro de jobs en memoria
  cache.py           # TTLCache, clave = sha256(lugar+fechas+intereses)
  validation.py      # Validación de input antes de gastar API
prompts/
  investigacion_v1.md
  eventos_v1.md
evals/
  casos.py           # 8 casos dorados
  aserciones.py      # Validaciones automáticas
  resultados/        # Un archivo por versión de prompt
tests/
  fixtures/          # Respuestas crudas de la API, grabadas
frontend/
docs/
  plan_agente_viajes_v2.md
  instrucciones_proyecto_claude.md
  decisiones.md       # Registro de decisiones de diseño no obvias
```

## Comandos

```bash
pytest                      # tests unitarios (usan fixtures, no red)
python -m evals.run         # harness de evals — consume API
flask --app app run --debug
```

## Convenciones

- Python: type hints en todo lo público. Pydantic para cualquier frontera de datos.
- Errores: nunca `except: pass`. Si un fallo se traga, se loguea con contexto.
- Nombres de dominio en español (`imprescindibles`, `segun_intereses`), nombres de infraestructura en inglés (`cache`, `jobs`, `retry`). Es la convención existente del proyecto — mantenerla.
- Commits: qué cambió y por qué. Si cambia un prompt, incluir el delta de la métrica de evals en el mensaje.
- Nada de secretos en el repo. `ANTHROPIC_API_KEY` va en `.env`, y `.env` va en `.gitignore` desde el primer commit.

## Antes de dar una tarea por terminada

- [ ] `pytest` en verde
- [ ] Si tocaste prompts o schema: evals corridos y resultado guardado
- [ ] Sin llamadas a la API dentro de tests unitarios
- [ ] Ningún schema duplicado a mano
