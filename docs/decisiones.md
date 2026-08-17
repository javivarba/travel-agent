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
