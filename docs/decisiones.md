# Decisiones

Registro de decisiones de diseño que no son obvias leyendo el código: qué se
eligió, por qué, y qué alternativa se descartó a propósito. No es un
changelog — es para que nadie (ni yo en seis meses) "corrija" algo que ya se
pensó y se descartó a conciencia.

---

## 2026-08-17 — `allowed_callers: ["direct"]` en la tool de búsqueda

**Qué:** se agregó `"allowed_callers": ["direct"]` al dict `tool_busqueda` en
`_llamar()` (`app/agent.py`), y se documentó en el plan (§7.1, §7.2).

**Por qué:** el default de la API para `web_search_20260318` es
`allowed_callers: ["code_execution_20260120"]`. Con ese default, dynamic
filtering corre la búsqueda dentro de code execution y el bloque
`web_search_tool_result` queda anidado dentro de un `code_execution_tool_result`,
no en el primer nivel de `response.content`. `extraer_urls_consultadas()`
recorre `response.content` de forma plana: con el default devolvería un set
vacío, y `filtrar_por_fuente()` descartaría el 100% de los ítems — silencioso,
sin excepción, indistinguible de "la búsqueda no encontró nada".

**Qué se descartó:** el ahorro de tokens de dynamic filtering. Dynamic
filtering descarta contenido de los resultados de búsqueda antes de que
llegue al contexto del modelo. Eso mete una capa entre lo que la búsqueda
devolvió y lo que el modelo efectivamente vio — aunque se arreglara el parser
para leer la rama anidada, la garantía central del proyecto (que toda
`fuente_url` corresponda a una página que el modelo realmente consultó) queda
más débil: ya no se está verificando contra el registro completo de la
búsqueda, sino contra lo que sobrevivió al filtrado. No vale el ahorro.

---

## 2026-08-17 — `cobertura_de_categorias` mira las dos secciones, no solo `segun_intereses`

**Qué:** en `evals/aserciones.py`, `con_resultados` (la base de
`cobertura_de_categorias` y `sin_contradiccion_vacio_lleno`) pasó de
`{c for a in r.segun_intereses for c in a.categorias}` a
`{c for a in _actividades(r) for c in a.categorias}` — incluye
`imprescindibles`. Se limpió `tests/fixtures/01_manzanillo_cobertura_baja.json`
sacando las entradas de `naturaleza` y `fotografia_paisajes` de
`categorias_sin_resultados`, que eran un parche manual para esquivar este
mismo bug.

**Por qué:** el prompt (`prompts/investigacion_v1.md`) instruye que un ítem
que califica para las dos secciones va solo a `imprescindibles`. La aserción
original solo miraba `segun_intereses`, así que cualquier interés cubierto
legítimamente vía `imprescindibles` (frecuente en categorías populares como
`naturaleza` o `cultura_historia`) se marcaba como "ignorado en silencio" —
un falso positivo bloqueante por hacer exactamente lo que el prompt pide.

**Qué se descartó:** tocar el prompt para que declare explícitamente en
`categorias_sin_resultados` las categorías cubiertas vía `imprescindibles`.
Le mete al modelo una instrucción contraintuitiva ("declará como sin
resultados algo que sí tiene resultados, con una nota aclaratoria") y
corrompe el significado de `categorias_sin_resultados`, que debería
significar únicamente "no hay resultados" — no "hay resultados, pero en la
otra sección". El fixture original hacía justo eso como parche y quedaba
semánticamente contradictorio.

**Efecto colateral encontrado y corregido en el mismo commit:** ampliar
`con_resultados` a las dos secciones también alimentaba `sin_categorias_no_pedidas`
("intrusas"), que se rompía en el sentido contrario: un ítem de
`imprescindibles` con una categoría fuera de los intereses declarados (legítimo,
`imprescindibles` es independiente de los intereses por diseño) empezaba a
marcarse como intrusión. Esa aserción se dejó con su alcance original,
mirando solo `segun_intereses` — es la sección donde "categoría no pedida"
tiene sentido como fallo.

---

## 2026-08-17 — No unificar `CLAUDE.md` e `instrucciones_proyecto_claude.md`

**Qué:** los dos archivos siguen conviviendo con contenido parcialmente
superpuesto (bio del autor, cómo prefiere que se le ayude). No se fusionan
ni se hace que uno derive del otro.

**Por qué:** son mecanismos distintos, no una duplicación accidental.
`CLAUDE.md` lo lee Claude Code al trabajar en este repo. `docs/instrucciones_proyecto_claude.md`
es texto para pegar a mano en el campo de instrucciones de un proyecto de
claude.ai, donde se sube además `docs/plan_agente_viajes_v2.md` y `CLAUDE.md`
como conocimiento — un espacio de trabajo sin acceso al repo, para diseño y
prompts en vez de código.

**Qué se descartó:** generar `instrucciones_proyecto_claude.md` a partir de
`CLAUDE.md` (o viceversa) para eliminar la superposición. Son ~25 líneas;
sincronizarlas a mano cuesta menos que la indirección de mantener un paso de
generación para dos archivos cortos que además tienen audiencias distintas
(uno lo consume una herramienta, el otro lo pega una persona). Decisión
consciente — que quede registrada para que nadie lo "arregle" después
metiendo esa indirección.
