# Normalizacion de datos

Esta version deja el calculo IAFIS parametrizado por datos y preparado para migracion a base relacional o JSON.

## Archivos principales

- `data/formularios.csv`: formularios disponibles.
- `data/variables.csv`: preguntas por formulario.
- `data/opciones.csv`: opciones y valores asociados por `IdVariable`.
- `data/rangos_tickets.csv`: rangos asociados a la pregunta calculada por `IdPregunta`.
- `data/calculos_parametros.csv`: relacion entre una operacion calculada y las preguntas que usa.
- `data/modelo_normalizado.json`: representacion JSON funcional del modelo.
- `data/schema_relacional.sql`: estructura relacional sugerida.

## Contrato RANGO_TICKETS

La operacion `RANGO_TICKETS` no usa IDs fijos en codigo. Sus parametros se leen de `data/calculos_parametros.csv`:

- `CANTIDAD_TICKETS`
- `OPERACION_DELEGADA`
- `HORARIO_ATENCION`
- `DISPONIBILIDAD`
- `VALOR_UNITARIO`

Los porcentajes de horario y disponibilidad se leen desde `data/opciones.csv`, usando el `IdVariable` configurado en `calculos_parametros.csv`.

Los rangos de valor unitario se leen desde `data/rangos_tickets.csv`, usando como `IdPregunta` la pregunta calculada `VALOR_UNITARIO`.
