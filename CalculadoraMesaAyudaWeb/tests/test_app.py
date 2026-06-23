import unittest
from unittest.mock import patch
import re
import tempfile

import pandas as pd

from app import app, items_visibles_pdf, normalizar_valor_perfil, clave_texto, cotizaciones_por_mes_usuario


class AplicacionTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client=app.test_client()

    def autenticar(self, rol='Administrador'):
        with self.client.session_transaction() as sesion:
            sesion['usuario']='prueba'
            sesion['idusuario']=1
            sesion['rol']=rol
            sesion['_csrf_token']='token-prueba'

    def post_json(self, ruta, payload):
        return self.client.post(
            ruta,
            json=payload,
            headers={'X-CSRF-Token':'token-prueba'},
        )

    def test_inicio_muestra_administrador_y_cerrar_sesion_para_admin(self):
        self.autenticar()
        respuesta=self.client.get('/home')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertIn('/admin_login',html)
        self.assertIn('http://localhost:5000/login',html)
        self.assertIn('Cerrar Sesión',html)

    def test_inicio_oculta_administrador_para_usuario_no_admin(self):
        self.autenticar(rol='Operador')
        respuesta=self.client.get('/home')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertNotIn('/admin_login',html)
        self.assertNotIn('Administrador',html)
        self.assertIn('http://localhost:5000/login',html)

    def test_login_get_cierra_sesion_y_bloquea_regreso_a_formulario(self):
        self.autenticar()
        formulario=self.client.get('/formulario/200')
        self.assertEqual(formulario.status_code,200)
        self.assertIn('no-store',formulario.headers.get('Cache-Control',''))
        login=self.client.get('/login')
        self.assertEqual(login.status_code,200)
        regreso=self.client.get('/formulario/200')
        self.assertEqual(regreso.status_code,302)
        self.assertIn('/login',regreso.headers.get('Location',''))

    def test_guardar_cotizacion_mensaje_con_tildes_correctas(self):
        self.autenticar()
        with patch('app.calcular_cotizacion',return_value={'total':1000}), \
             patch('app.os.path.exists',return_value=False), \
             patch('pandas.core.generic.NDFrame.to_csv'):
            respuesta=self.post_json('/guardar_cotizacion',{'formulario_id':2,'respuestas':{}})
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        self.assertEqual(datos['mensaje'],'Cotización guardada correctamente')

    def rango_ticket_esperado(self, tickets, horario='5*8', disponibilidad='NO'):
        rangos=pd.read_csv('data/rangos_tickets.csv')
        total_tickets=float(tickets)
        rangos['DesdeNum']=pd.to_numeric(rangos['Desde'],errors='coerce')
        rangos['HastaNum']=pd.to_numeric(rangos['Hasta'],errors='coerce')
        coincidencia=rangos[
            (rangos['IdPregunta'].astype(str)=='50') &
            (rangos['DesdeNum']<=total_tickets) &
            (rangos['HastaNum']>=total_tickets)
        ].iloc[0]
        cantidad_cotizada=float(coincidencia['HastaNum'])
        if cantidad_cotizada>=999999999:
            cantidad_cotizada=total_tickets
        valor=float(coincidencia['Valor'])
        opciones=pd.read_csv('data/opciones.csv')
        def factor(id_variable, opcion):
            fila=opciones[
                (opciones['IdVariable'].astype(str)==str(id_variable)) &
                (opciones['Opcion'].astype(str).str.strip().str.upper()==str(opcion).strip().upper())
            ]
            return 1+(float(fila.iloc[0]['Valor'])/100) if not fila.empty else 1
        subtotal=round(cantidad_cotizada*valor*factor(48,horario)*factor(49,disponibilidad),2)
        try:
            cfg=pd.read_csv('data/configuracion_formularios.csv')
            cfg=cfg[(cfg['id_formulario'].astype(str)=='2') & (cfg['activo'].astype(str)=='1')]
            total=subtotal
            for _,c in cfg.iterrows():
                if str(c.get('tipo','')).upper().startswith('POR'):
                    total += subtotal*(float(c.get('valor',0))/100)
                else:
                    total += float(c.get('valor',0))
            return round(total,2)
        except Exception:
            return subtotal

    def test_ruta_administrativa_requiere_autenticacion(self):
        respuesta=self.client.get('/api/formularios')
        self.assertEqual(respuesta.status_code,401)

    def test_usuario_normal_no_puede_administrar(self):
        self.autenticar('Operador')
        respuesta=self.client.get('/api/formularios')
        self.assertEqual(respuesta.status_code,403)

    def test_csrf_es_obligatorio(self):
        self.autenticar()
        respuesta=self.client.post('/formulario_crear',data={'nombre':'Prueba CSRF'})
        self.assertEqual(respuesta.status_code,400)

    def test_rutas_de_rangos_se_registran(self):
        self.autenticar()
        respuesta=self.client.get('/api/rangos')
        self.assertEqual(respuesta.status_code,200)

    def test_api_rangos_carga_configuracion_de_pregunta_50(self):
        self.autenticar()
        respuesta=self.client.get('/api/rangos?idPregunta=50')
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        self.assertTrue(datos['ok'])
        self.assertGreaterEqual(len(datos['rangos']),3)
        rangos=pd.read_csv('data/rangos_tickets.csv')
        primer_rango=rangos[rangos['IdPregunta'].astype(str)=='50'].iloc[0]
        self.assertEqual(str(datos['rangos'][0]['desde']),str(primer_rango['Desde']))
        self.assertEqual(str(datos['rangos'][0]['hasta']),str(primer_rango['Hasta']))
        self.assertEqual(str(datos['rangos'][0]['valor']),str(primer_rango['Valor']))

    def test_admin_precarga_rangos_de_pregunta_50(self):
        self.autenticar()
        respuesta=self.client.get('/cuestionario_admin?vista=preguntas&formulario=2')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertIn('RANGOS_CONFIGURADOS',html)
        self.assertIn('"50"',html)
        rangos=pd.read_csv('data/rangos_tickets.csv')
        primer_rango=rangos[rangos['IdPregunta'].astype(str)=='50'].iloc[0]
        self.assertIn(f'"desde": "{primer_rango["Desde"]}"',html)
        self.assertIn(f'"hasta": "{primer_rango["Hasta"]}"',html)
        self.assertIn(f'"valor": "{primer_rango["Valor"]}"',html)

    def test_admin_muestra_operaciones_de_pregunta(self):
        self.autenticar()
        respuesta=self.client.get('/cuestionario_admin?admin=1&vista=formularios')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertIn('value="FIJO"',html)
        self.assertIn('value="SUMAR"',html)
        self.assertIn('value="MULTIPLICAR"',html)
        self.assertIn('value="RANGO_TICKETS"',html)
        self.assertIn('value="PORCENTAJE"',html)
        self.assertIn('value="SERVICIOS_EXCEL"',html)
        self.assertIn('actualizarFactorPorTipo',html)
        self.assertIn('/calculada_config_admin/',html)

    def test_popup_opciones_no_muestra_texto_mal_codificado(self):
        self.autenticar()
        respuesta=self.client.get('/opciones_admin/48')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertIn('Opciones 48',html)
        self.assertIn('>Agregar</button>',html)
        self.assertNotIn('â',html)
        self.assertNotIn('Ã',html)
        self.assertNotIn('вљ',html)

    def test_config_calculada_generica_soporta_rangos_y_servicios(self):
        self.autenticar()
        rangos=self.client.get('/calculada_config_admin/50')
        self.assertEqual(rangos.status_code,200)
        html_rangos=rangos.get_data(as_text=True)
        self.assertIn('RANGO_TICKETS',html_rangos)
        self.assertIn('Parametros de entrada y salida',html_rangos)
        self.assertIn('Cantidad de Tickets',html_rangos)
        self.assertIn('Valor Base',html_rangos)
        self.assertIn("name='param_CANTIDAD_TICKETS'",html_rangos)
        servicios=self.client.get('/calculada_config_admin/2005')
        self.assertEqual(servicios.status_code,200)
        html_servicios=servicios.get_data(as_text=True)
        self.assertIn('SERVICIOS_EXCEL',html_servicios)
        self.assertIn('Parametros de entrada y salida',html_servicios)
        self.assertIn('PRODUCTO_SERVICIO',html_servicios)
        self.assertIn("name='param_PRODUCTO_SERVICIO'",html_servicios)
        self.assertIn("name='cfg_APLICAR_DISPONIBILIDAD'",html_servicios)

    def test_config_calculada_generica_soporta_todas_las_operaciones(self):
        self.autenticar()
        casos={
            3004:'FIJO',
            3005:'SUMAR',
            3006:'MULTIPLICAR',
            3007:'PORCENTAJE',
            50:'RANGO_TICKETS',
            2005:'SERVICIOS_EXCEL',
            10511:'MULTIPLICAR',
        }
        for pregunta_id, operacion in casos.items():
            with self.subTest(pregunta_id=pregunta_id, operacion=operacion):
                respuesta=self.client.get(f'/calculada_config_admin/{pregunta_id}')
                self.assertEqual(respuesta.status_code,200)
                html=respuesta.get_data(as_text=True)
                self.assertIn(operacion,html)
                self.assertNotIn('no tiene una operacion definida',html)
                if operacion in ('FIJO','SUMAR','MULTIPLICAR','PORCENTAJE'):
                    self.assertIn('Preguntas origen',html)
                    self.assertIn("name='operand_id'",html)
                else:
                    self.assertIn('Parametros de entrada y salida',html)

    def test_calculadas_genericas_calculan_con_varias_preguntas_origen(self):
        self.autenticar()
        payload={
            'formulario_id':300,
            'respuestas':{
                '3001':10,
                '3002':20,
                '3003':25,
            },
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        data=respuesta.get_json()
        self.assertEqual(data['total'],272.25)
        valores={item['pregunta']:item['valor'] for item in data['items']}
        self.assertEqual(valores['Calculo Fijo'],10)
        self.assertEqual(valores['Calculo Sumar'],30)
        self.assertEqual(valores['Calculo Multiplicar'],200)
        self.assertEqual(valores['Calculo Porcentaje'],7.5)
        visibles=items_visibles_pdf(data['items'])
        self.assertNotIn('Ganancia Prueba',[item['pregunta'] for item in visibles])
        self.assertEqual(data['categorias']['Calculadas'],272.25)

    def test_formulario_nuevo_prueba_todas_las_calculadas(self):
        self.autenticar()
        pagina=self.client.get('/formulario/301').get_data(as_text=True)
        self.assertIn('Base A',pagina)
        self.assertIn('Cantidad de Tickets',pagina)
        self.assertIn('Producto Servicio',pagina)
        self.assertNotIn('Agregar producto/servicio',pagina)
        casos={
            30111:'FIJO',
            30112:'SUMAR',
            30113:'MULTIPLICAR',
            30114:'PORCENTAJE',
            30115:'RANGO_TICKETS',
            30116:'SERVICIOS_EXCEL',
        }
        for pregunta_id, operacion in casos.items():
            with self.subTest(pregunta_id=pregunta_id):
                respuesta=self.client.get(f'/calculada_config_admin/{pregunta_id}')
                self.assertEqual(respuesta.status_code,200)
                html=respuesta.get_data(as_text=True)
                self.assertIn(operacion,html)
                self.assertNotIn('no tiene una operacion definida',html)

        payload={
            'formulario_id':301,
            'respuestas':{
                '30101':10,
                '30102':20,
                '30103':25,
                '30104':10,
                '30105':5,
                '30106':'5*8',
                '30107':'NO',
            },
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        data=respuesta.get_json()
        self.assertEqual(data['total'],100247.5)
        valores={item['pregunta']:item['valor'] for item in data['items']}
        self.assertEqual(valores['Prueba Fijo'],10)
        self.assertEqual(valores['Prueba Sumar'],30)
        self.assertEqual(valores['Prueba Multiplicar'],200)
        self.assertEqual(valores['Prueba Porcentaje'],7.5)
        self.assertEqual(valores['Tickets y Operación Delegada ingresados'],100000)

        servicios={
            'formulario_id':301,
            'servicios':[{
                'producto_servicio':'BD',
                'perfil':'BD. Junior Prueba',
                'porcentaje':100,
                'disponibilidad':'7X24',
            }],
        }
        respuesta_servicios=self.post_json('/calcular',servicios)
        self.assertEqual(respuesta_servicios.status_code,200)
        data_servicios=respuesta_servicios.get_json()
        self.assertEqual(data_servicios['total'],1350000.0)

    def test_formularios_mixtos_de_prueba_tienen_diez_preguntas(self):
        formularios=pd.read_csv('data/formularios.csv')
        variables=pd.read_csv('data/variables.csv')
        for formulario_id in range(101,106):
            self.assertTrue((formularios['IdFormulario'].astype(str)==str(formulario_id)).any())
            preguntas=variables[variables['IdFormulario'].astype(str)==str(formulario_id)]
            self.assertEqual(len(preguntas),10)
            self.assertIn('NUMERO',set(preguntas['Tipo'].astype(str)))
            self.assertIn('LISTA',set(preguntas['Tipo'].astype(str)))
            self.assertIn('CALCULADA',set(preguntas['Tipo'].astype(str)))
            self.assertIn('RANGO_TICKETS',set(preguntas['Operacion'].astype(str)))
            self.assertIn('PORCENTAJE',set(preguntas['Operacion'].astype(str)))

    def test_admin_formularios_no_duplica_ids_de_preguntas(self):
        self.autenticar()
        respuesta=self.client.get('/cuestionario_admin?admin=1&vista=formularios')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertEqual(html.count('id="frmPreguntas"'),1)
        self.assertEqual(html.count('id="preguntasBody"'),1)

    def test_api_formularios_carga_datos_para_preguntas(self):
        self.autenticar()
        respuesta=self.client.get('/api/formularios')
        self.assertEqual(respuesta.status_code,200)
        nombres=[f['Nombre'] for f in respuesta.get_json()]
        self.assertIn('Mesa de Ayuda',nombres)
        self.assertIn('Mesa de Ayuda IAFIS',nombres)

    def test_operacion_porcentaje_en_pregunta_numerica(self):
        self.autenticar()
        variables=pd.DataFrame([
            {
                'IdVariable':99,
                'IdFormulario':9,
                'Categoria':'Prueba',
                'Variable':'Porcentaje prueba',
                'Tipo':'NUMERO',
                'Operacion':'PORCENTAJE',
                'Factor':10,
                'Estado':'Activo',
                'Visible':1,
            }
        ])
        vacio=pd.DataFrame(columns=['IdVariable','Opcion','Valor'])

        def leer_csv(ruta,*args,**kwargs):
            if str(ruta).endswith('variables.csv'):
                return variables.copy()
            if str(ruta).endswith('opciones.csv'):
                return vacio.copy()
            if str(ruta).endswith('usuarios_formularios.csv'):
                return pd.DataFrame([{'IdUsuario':1,'IdFormulario':9}])
            if str(ruta).endswith('formularios.csv'):
                return pd.DataFrame([{'IdFormulario':9,'Nombre':'Prueba'}])
            return pd.DataFrame()

        with patch('app.pd.read_csv',side_effect=leer_csv):
            respuesta=self.post_json('/calcular',{'formulario_id':9,'respuestas':{'99':200}})
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.get_json()['total'],20)

    def test_operacion_porcentaje_en_lista_aplica_sobre_subtotal(self):
        self.autenticar()
        variables=pd.DataFrame([
            {
                'IdVariable':98,
                'IdFormulario':9,
                'Categoria':'Base',
                'Variable':'Base mensual',
                'Tipo':'NUMERO',
                'Operacion':'FIJO',
                'Factor':0,
                'Estado':'Activo',
                'Visible':1,
            },
            {
                'IdVariable':99,
                'IdFormulario':9,
                'Categoria':'Servicio',
                'Variable':'Idioma',
                'Tipo':'LISTA',
                'Operacion':'PORCENTAJE',
                'Factor':0,
                'Estado':'Activo',
                'Visible':1,
            },
        ])
        opciones=pd.DataFrame([
            {'IdVariable':99,'Opcion':'Español','Valor':0},
            {'IdVariable':99,'Opcion':'Ingles','Valor':25},
        ])

        def leer_csv(ruta,*args,**kwargs):
            if str(ruta).endswith('variables.csv'):
                return variables.copy()
            if str(ruta).endswith('opciones.csv'):
                return opciones.copy()
            if str(ruta).endswith('usuarios_formularios.csv'):
                return pd.DataFrame([{'IdUsuario':1,'IdFormulario':9}])
            if str(ruta).endswith('formularios.csv'):
                return pd.DataFrame([{'IdFormulario':9,'Nombre':'Prueba'}])
            return pd.DataFrame()

        with patch('app.pd.read_csv',side_effect=leer_csv):
            respuesta=self.post_json('/calcular',{'formulario_id':9,'respuestas':{'98':1000,'99':'Ingles'}})
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        self.assertEqual(datos['total'],1250)
        self.assertEqual(datos['items'][1]['valor'],250)

    def test_dashboard_admin_renderiza_sin_exponer_hashes(self):
        self.autenticar()
        respuesta=self.client.get('/cuestionario_admin')
        self.assertEqual(respuesta.status_code,200)
        self.assertNotIn(b'scrypt:',respuesta.data)
        self.assertNotIn(b'pbkdf2:',respuesta.data)

    def test_dashboard_cotizaciones_por_mes(self):
        self.autenticar()
        respuesta=self.client.get('/cuestionario_admin?admin=1&vista=dashboard')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        _,datasets=cotizaciones_por_mes_usuario()
        dataset_sin_usuario=[d for d in datasets if d['label']=='Sin usuario'][0]
        self.assertIn('chartCotizaciones',html)
        self.assertIn('cotizaciones',html)
        self.assertIn('Sin usuario',html)
        self.assertIn(str(dataset_sin_usuario['data'][5]),html)

    def test_cotizaciones_por_mes_usuario_cuenta_registros_no_valores(self):
        datos=pd.DataFrame([
            {'fecha':'2026-05-01 10:00:00','total':100000,'usuario':'ana','idusuario':1},
            {'fecha':'2026-05-02 10:00:00','total':900000,'usuario':'ana','idusuario':1},
            {'fecha':'2026-05-03 10:00:00','total':500000,'usuario':'luis','idusuario':2},
            {'fecha':'2026-06-01 10:00:00','total':700000,'usuario':'luis','idusuario':2},
        ])
        with tempfile.NamedTemporaryFile(mode='w',suffix='.csv',delete=False,encoding='utf-8',newline='') as tmp:
            ruta=tmp.name
            datos.to_csv(tmp,index=False)
        try:
            labels,datasets=cotizaciones_por_mes_usuario(ruta)
        finally:
            import os
            os.remove(ruta)
        self.assertEqual(labels[4],'May')
        por_usuario={dataset['label']:dataset['data'] for dataset in datasets}
        self.assertEqual(por_usuario['ana'][4],2)
        self.assertEqual(por_usuario['luis'][4],1)
        self.assertEqual(por_usuario['luis'][5],1)

    def test_crear_pregunta_factor_vacio_guarda_cero(self):
        self.autenticar()
        variables=pd.DataFrame([{
            'IdVariable':1,
            'IdFormulario':1,
            'Categoria':'Base',
            'Variable':'Existente',
            'Tipo':'LISTA',
            'Operacion':'FIJO',
            'Factor':0,
            'Estado':'Activo',
            'Visible':1,
        }])

        def leer_csv(ruta,*args,**kwargs):
            if str(ruta).endswith('variables.csv'):
                return variables
            return pd.DataFrame()

        with patch('app.pd.read_csv',side_effect=leer_csv), patch('pandas.core.generic.NDFrame.to_csv'):
            respuesta=self.client.post('/pregunta_editar',data={
                'formulario_id':'1',
                'categoria':'Prueba',
                'variable':'Factor vacio',
                'tipo':'LISTA',
                'operacion':'FIJO',
                'factor':'',
                'visible':'1',
                '_csrf_token':'token-prueba',
            })
        self.assertEqual(respuesta.status_code,302)
        self.assertEqual(float(variables.iloc[-1]['Factor']),0)

    def test_formulario_uno_no_incluye_calculo_del_formulario_dos(self):
        self.autenticar()
        respuesta=self.post_json('/calcular',{'formulario_id':1,'respuestas':{}})
        self.assertEqual(respuesta.status_code,200)
        preguntas=[item['pregunta'] for item in respuesta.get_json()['items']]
        self.assertNotIn('Valor mensual',preguntas)
        self.assertEqual(respuesta.get_json()['total'],0)

    def test_valor_mensual_de_tickets(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':50,'47':0,'48':'5*8','49':'NO'},
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.get_json()['total'],self.rango_ticket_esperado(50,'5*8','NO'))

    def test_iafis_no_calcula_total_si_cantidades_estan_vacias(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':'','47':'','48':'5*8','49':'SI'},
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        data=respuesta.get_json()
        self.assertEqual(data['total'],0)
        preguntas=[item['pregunta'] for item in data['items']]
        self.assertNotIn('Valor mensual',preguntas)

    def test_pantalla_no_muestra_nan_si_calculo_devuelve_error(self):
        self.autenticar()
        respuesta=self.client.get('/formulario/2')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertIn('Number.isFinite(totalCalculado)',html)
        self.assertIn("d.total=0",html)
        self.assertNotIn("Number(d.total).toLocaleString('es-CO');",html)

    def test_valor_mensual_suma_tickets_delegados(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':100,'47':50,'48':'5*8','49':'NO'},
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.get_json()['total'],self.rango_ticket_esperado(150,'5*8','NO'))

    def test_valor_unitario_ticket_no_aparece_en_formulario(self):
        self.autenticar()
        respuesta=self.client.get('/formulario/2')
        self.assertEqual(respuesta.status_code,200)
        self.assertNotIn('Valor Unitario Ticket'.encode(),respuesta.data)

    def test_pregunta_50_esta_marcada_como_invisible(self):
        self.autenticar()
        respuesta=self.client.get('/api/preguntas/2')
        self.assertEqual(respuesta.status_code,200)
        pregunta_50=[p for p in respuesta.get_json() if str(p['IdVariable'])=='50'][0]
        self.assertEqual(str(pregunta_50['Visible']),'0')

    def test_valor_mensual_aplica_horario_y_disponibilidad(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':201,'47':0,'48':'7*24','49':'SI'},
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.get_json()['total'],self.rango_ticket_esperado(201,'7*24','SI'))

    def test_disponibilidad_usa_porcentaje_configurado_en_opciones(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':10,'47':0,'48':'5*8','49':'SI','51':''},
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.get_json()['total'],self.rango_ticket_esperado(10,'5*8','SI'))

    def test_texto_costos_pdf_iafis_muestra_rango_y_valor_ticket(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':10,'47':10,'48':'5*8','49':'SI'},
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        items=respuesta.get_json()['items']
        costos=[i for i in items if i['pregunta']=='Tickets y Operación Delegada ingresados'][0]
        self.assertIn('20; cotización en rango 0 a 150; valor por ticket con características seleccionadas:',costos['respuesta'])

    def test_pdf_se_genera_en_memoria(self):
        self.autenticar()
        payload={
            'formulario_id':2,
            'respuestas':{'46':100,'47':0,'48':'5*8','49':'NO'},
        }
        respuesta=self.post_json('/generar_pdf',payload)
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.mimetype,'application/pdf')
        self.assertTrue(respuesta.data.startswith(b'%PDF'))

    def test_pdf_usa_total_antes_de_iva(self):
        with open('app.py',encoding='utf-8') as archivo:
            fuente=archivo.read()
        self.assertIn('TOTAL COTIZACIÓN ANTES DE IVA',fuente)
        self.assertNotIn("TOTAL COTIZACIÓN: ${total",fuente)

    def test_formulario_excel_servicios_carga_boton_agregar(self):
        self.autenticar()
        respuesta=self.client.get('/formulario/200')
        self.assertEqual(respuesta.status_code,200)
        html=respuesta.get_data(as_text=True)
        self.assertIn('Calculadora QBITIC Servicios',html)
        self.assertIn('Agregar producto/servicio',html)
        self.assertIn('BD. Senior (Administraci\\u00f3n',html)
        self.assertIn('BD. Junior (Tareas de Operaci\\u00f3n)',html)
        self.assertNotIn('OperaciÃ',html)
        self.assertNotIn('AdministraciÃ',html)
        self.assertIn('Complete Producto/Servicio, Perfil y Porcentaje',html)
        self.assertIn('validarServiciosCompletos',html)
        admin=self.client.get('/cuestionario_admin?admin=1&vista=preguntas&formulario=200').get_data(as_text=True)
        self.assertIn('Configurar Calculo',admin)
        config=self.client.get('/calculada_config_admin/2005').get_data(as_text=True)
        self.assertIn('Formula:',config)
        self.assertIn('Logica:',config)
        self.assertIn('PRODUCTO_SERVICIO',config)
        self.assertIn('APLICAR_DISPONIBILIDAD',config)
        self.assertNotIn('Impuesto %',config)
        self.assertNotIn('Margen %',config)
        redireccion=self.client.get('/opciones_admin/2005')
        self.assertEqual(redireccion.status_code,302)
        self.assertIn('/servicios_config_admin/200',redireccion.headers['Location'])
        por_pregunta=self.client.get('/servicios_config_admin_pregunta/2005')
        self.assertEqual(por_pregunta.status_code,302)
        self.assertIn('/servicios_config_admin/200',por_pregunta.headers['Location'])

    def test_calculadora_excel_servicios_repara_tildes_para_pdf(self):
        self.autenticar()
        payload={
            'formulario_id':200,
            'servicios':[
                {
                    'producto_servicio':'BD',
                    'perfil':'BD. Junior (Tareas de Operación)',
                    'porcentaje':100,
                    'disponibilidad':'5X7',
                }
            ],
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        servicio=[i for i in datos['items'] if i['categoria']=='Servicio'][0]
        self.assertIn('BD. Junior (Tareas de Operación)',servicio['respuesta'])
        self.assertNotIn('OperaciÃ',servicio['respuesta'])
        self.assertNotIn('AdministraciÃ',servicio['respuesta'])

    def test_calculadora_excel_servicios_suma_varias_lineas(self):
        self.autenticar()
        payload={
            'formulario_id':200,
            'servicios':[
                {
                    'producto_servicio':'BD',
                    'perfil':'BD. Senior (Administración y Soporte N1/N2)',
                    'porcentaje':100,
                    'disponibilidad':'5X7',
                },
                {
                    'producto_servicio':'SO',
                    'perfil':'SO. Master (Administración y Soporte N3)',
                    'porcentaje':50,
                    'disponibilidad':'7X24',
                },
            ],
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        linea_1=12384167
        linea_2=(15784167*0.50)*1.35
        subtotal=linea_1+linea_2
        esperado=31101947.62
        self.assertEqual(datos['total'],esperado)
        self.assertEqual(len([i for i in datos['items'] if i['categoria']=='Servicio']),2)

    def test_calculadora_excel_calcula_sin_disponibilidad(self):
        self.autenticar()
        payload={
            'formulario_id':200,
            'servicios':[
                {
                    'producto_servicio':'BD',
                    'perfil':'BD. Junior (Tareas de Operación)',
                    'porcentaje':100,
                    'disponibilidad':'',
                }
            ],
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        self.assertEqual(datos['total'],round(8134167*1.35,2))
        self.assertEqual(len([i for i in datos['items'] if i['categoria']=='Servicio']),1)

    def test_calculadora_excel_no_calcula_linea_incompleta(self):
        self.autenticar()
        payload={
            'formulario_id':200,
            'servicios':[
                {
                    'producto_servicio':'BD',
                    'perfil':'',
                    'porcentaje':100,
                    'disponibilidad':'7X24',
                }
            ],
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        self.assertEqual(datos['total'],0)
        self.assertEqual(len([i for i in datos['items'] if i['categoria']=='Servicio']),0)

    def test_pdf_calculadora_excel_no_muestra_configuracion(self):
        self.autenticar()
        payload={
            'formulario_id':200,
            'servicios':[
                {
                    'producto_servicio':'BD',
                    'perfil':'BD. Junior (Tareas de Operación)',
                    'porcentaje':100,
                    'disponibilidad':'7X24',
                }
            ],
        }
        respuesta=self.post_json('/calcular',payload)
        self.assertEqual(respuesta.status_code,200)
        datos=respuesta.get_json()
        visibles=items_visibles_pdf(datos['items'])
        preguntas=[item['pregunta'] for item in visibles]
        categorias=[item['categoria'] for item in visibles]
        self.assertIn('Servicio 1',preguntas)
        self.assertNotIn('Impuesto',preguntas)
        self.assertNotIn('Imprevistos',preguntas)
        self.assertNotIn('Margen',preguntas)
        self.assertNotIn('Configuracion',categorias)

    def test_perfil_servicios_muestra_valor_y_actualiza_tarifa(self):
        self.autenticar()
        opciones=pd.read_csv('data/opciones.csv')
        perfil=opciones[
            (opciones['IdVariable'].astype(str)=='2002')
            & (opciones['Opcion'].astype(str).map(clave_texto)==clave_texto('BD. Junior (Tareas de Operación)'))
        ].iloc[0]
        self.assertEqual(float(perfil['Valor']),8134167)
        with patch('app.pd.read_csv') as leer_csv, patch('pandas.core.generic.NDFrame.to_csv'), patch('app.sincronizar_valor_tarifa_perfil') as sincronizar:
            opciones_mock=pd.DataFrame([
                {'IdVariable':2002,'Opcion':'BD. Junior (Tareas de Operación)','Valor':8134167},
            ])
            def cargar(path,*args,**kwargs):
                if str(path).endswith('opciones.csv'):
                    return opciones_mock
                return pd.DataFrame()
            leer_csv.side_effect=cargar
            respuesta=self.client.post(
                '/opcion_editar/2002/BD. Junior (Tareas de Operación)',
                data={
                    'opcion':'BD. Junior (Tareas de Operación)',
                    'valor':'9000000',
                    '_csrf_token':'token-prueba',
                },
            )
        self.assertEqual(respuesta.status_code,302)
        self.assertEqual(float(opciones_mock.iloc[0]['Valor']),9000000)
        sincronizar.assert_called_once_with(2002,'BD. Junior (Tareas de Operación)',9000000)

    def test_perfil_servicios_valor_corto_se_interpreta_en_millones(self):
        self.assertEqual(normalizar_valor_perfil(2002,10),10000000)
        self.assertEqual(normalizar_valor_perfil(2002,8.5),8500000)
        self.assertEqual(normalizar_valor_perfil(2002,8134167),8134167)


if __name__=='__main__':
    unittest.main()
