CREATE TABLE formularios (
  id_formulario INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  descripcion TEXT,
  activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE preguntas (
  id_pregunta INTEGER PRIMARY KEY,
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  categoria TEXT NOT NULL,
  pregunta TEXT NOT NULL,
  tipo TEXT NOT NULL,
  operacion TEXT NOT NULL DEFAULT 'FIJO',
  factor NUMERIC DEFAULT 0,
  estado TEXT NOT NULL DEFAULT 'Activo',
  visible INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE opciones (
  id_opcion INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_pregunta INTEGER NOT NULL REFERENCES preguntas(id_pregunta),
  opcion TEXT NOT NULL,
  valor NUMERIC NOT NULL DEFAULT 0
);

CREATE TABLE rangos_pregunta (
  id_rango INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_pregunta INTEGER NOT NULL REFERENCES preguntas(id_pregunta),
  desde NUMERIC NOT NULL,
  hasta NUMERIC NOT NULL,
  valor NUMERIC NOT NULL
);

CREATE TABLE servicios_tarifas (
  id_tarifa INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  producto_servicio TEXT NOT NULL,
  perfil TEXT NOT NULL,
  salario_total NUMERIC NOT NULL,
  descripcion_perfil TEXT,
  UNIQUE (id_formulario, producto_servicio, perfil)
);

CREATE TABLE servicios_config (
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  parametro TEXT NOT NULL,
  valor NUMERIC NOT NULL,
  PRIMARY KEY (id_formulario, parametro)
);

CREATE TABLE servicios_cotizados (
  id_servicio_cotizado INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_cotizacion INTEGER NOT NULL,
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  producto_servicio TEXT NOT NULL,
  perfil TEXT NOT NULL,
  porcentaje NUMERIC NOT NULL,
  disponibilidad TEXT NOT NULL,
  salario_base NUMERIC NOT NULL,
  valor_servicio NUMERIC NOT NULL,
  recargo_disponibilidad NUMERIC NOT NULL,
  total_linea NUMERIC NOT NULL
);

CREATE TABLE calculos_operaciones (
  operacion TEXT PRIMARY KEY,
  titulo TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  formula TEXT NOT NULL,
  usa_rangos INTEGER NOT NULL DEFAULT 0,
  usa_parametros INTEGER NOT NULL DEFAULT 1,
  usa_configuracion INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE calculos_parametros_def (
  operacion TEXT NOT NULL REFERENCES calculos_operaciones(operacion),
  parametro TEXT NOT NULL,
  etiqueta TEXT NOT NULL,
  descripcion TEXT,
  requerido INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (operacion, parametro)
);

CREATE TABLE calculos_config_def (
  operacion TEXT NOT NULL REFERENCES calculos_operaciones(operacion),
  parametro TEXT NOT NULL,
  etiqueta TEXT NOT NULL,
  tipo TEXT NOT NULL,
  valor_default NUMERIC,
  opciones TEXT,
  descripcion TEXT,
  PRIMARY KEY (operacion, parametro)
);

CREATE TABLE calculos_config (
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  operacion TEXT NOT NULL REFERENCES calculos_operaciones(operacion),
  parametro TEXT NOT NULL,
  valor NUMERIC NOT NULL,
  PRIMARY KEY (id_formulario, operacion, parametro)
);

CREATE TABLE calculos_parametros (
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  operacion TEXT NOT NULL,
  parametro TEXT NOT NULL,
  id_pregunta INTEGER NOT NULL REFERENCES preguntas(id_pregunta),
  PRIMARY KEY (id_formulario, operacion, parametro)
);

CREATE TABLE usuarios (
  id_usuario INTEGER PRIMARY KEY,
  usuario TEXT NOT NULL UNIQUE,
  clave TEXT NOT NULL,
  nombre TEXT,
  rol TEXT NOT NULL,
  activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE usuarios_formularios (
  id_usuario INTEGER NOT NULL REFERENCES usuarios(id_usuario),
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  PRIMARY KEY (id_usuario, id_formulario)
);

CREATE TABLE configuracion_formularios (
  id_configuracion INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_formulario INTEGER NOT NULL REFERENCES formularios(id_formulario),
  concepto TEXT NOT NULL,
  tipo TEXT NOT NULL,
  valor NUMERIC NOT NULL DEFAULT 0,
  activo INTEGER NOT NULL DEFAULT 1
);
