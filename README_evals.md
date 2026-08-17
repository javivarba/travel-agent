# Harness de evals

## Uso

```bash
python -m pytest tests/                    # tests de las aserciones, sin API
python -m evals.runner --fixtures          # corre los casos offline
python -m evals.runner --version v1 --n 3  # corrida real, 3 repeticiones por caso
python -m evals.runner --casos 06_puerto_viejo_solo_pesca --grabar
python -m evals.runner --comparar v1 v2    # compara las últimas corridas
```

`ANTHROPIC_API_KEY` en `.env`. Sale con código 1 si algún caso no pasa el 100%,
así que sirve directo en un hook de pre-commit o en CI.

## Orden de trabajo recomendado

1. `--fixtures` mientras desarrollás aserciones. Cero costo.
2. `--casos X --grabar` para refrescar un fixture cuando cambia el schema.
3. `--n 3` completo solo antes de promover una versión de prompt.

## Qué mirar

| Métrica | Significa |
|---|---|
| Tasa de paso por caso | 3/3 confiable · 2/3 inestable · 0/3 roto. Un 2/3 no es "casi bien": es un prompt que falla un tercio de las veces |
| Tasa de descarte | Proporción de ítems eliminados por fuente no verificable. Sube = el prompt inventa más |
| Juez | Calidad subjetiva 1–5. Solo comparable entre corridas con la misma rúbrica |

## Promover una versión de prompt

1. `cp prompts/investigacion_v1.md prompts/investigacion_v2.md` y editar
2. `python -m evals.runner --version v2 --n 3`
3. `python -m evals.runner --comparar v1 v2`
4. Promover solo si tasa de paso sube o se mantiene **y** tasa de descarte no sube
5. El delta va en el mensaje del commit
