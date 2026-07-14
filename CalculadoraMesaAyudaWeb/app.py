from flask import Flask, render_template, request, jsonify, session, redirect, send_file
import pandas as pd, os
import hmac
import io
import json
import re
import secrets
import unicodedata
from functools import wraps
from pathlib import Path
from markupsafe import escape
from urllib.parse import quote
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

app=Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)


def _is_password_hash(value):
    return str(value).startswith(('scrypt:', 'pbkdf2:'))


def _authenticate_user(usuario, clave):
    path='data/usuarios.csv'
    usuarios=pd.read_csv(path).fillna('')
    columnas={str(c).strip().lower():c for c in usuarios.columns}
    usuario_col=columnas.get('usuario')
    clave_col=columnas.get('clave')
    if not usuario_col or not clave_col:
        return None
    encontrados=usuarios[usuarios[usuario_col].astype(str)==str(usuario)]
    if encontrados.empty:
        return None
    row_original=encontrados.iloc[0]
    activo_col=columnas.get('activo')
    if activo_col and str(row_original.get(activo_col, '1')).strip().lower() in ('0', 'false', 'no'):
        return None
    almacenada=str(row_original.get(clave_col, ''))
    valida=check_password_hash(almacenada, clave) if _is_password_hash(almacenada) else hmac.compare_digest(almacenada, str(clave))
    if not valida:
        return None
    if not _is_password_hash(almacenada):
        usuarios.loc[encontrados.index[0], clave_col]=generate_password_hash(str(clave))
        usuarios.to_csv(path,index=False)
        row_original=usuarios.loc[encontrados.index[0]]
    return pd.Series({nombre:row_original.get(original,'') for nombre,original in columnas.items()})


def _unauthorized(status=401):
    if request.path.startswith('/api/') or request.is_json or request.headers.get('X-Requested-With')=='XMLHttpRequest':
        return jsonify({'ok':False,'error':'No autorizado'}),status
    return redirect('/login') if status==401 else ('Acceso denegado. Solo Administradores.',403)


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not auth():
            return _unauthorized(401)
        return func(*args, **kwargs)
    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not auth():
            return _unauthorized(401)
        if not es_admin():
            return _unauthorized(403)
        return func(*args, **kwargs)
    return wrapper


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token']=secrets.token_urlsafe(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token']=csrf_token


@app.before_request
def protect_csrf():
    if request.path == '/logout':
        return None
    if request.method in ('POST','PUT','PATCH','DELETE'):
        enviado=request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token','')
        esperado=session.get('_csrf_token','')
        if not esperado or not hmac.compare_digest(str(enviado),str(esperado)):
            if not (request.path.startswith('/api/') or request.is_json or request.headers.get('X-Requested-With')=='XMLHttpRequest'):
                session.clear()
                return redirect('/login')
            return jsonify({'ok':False,'error':'Token CSRF inválido'}),400

@app.after_request
def evitar_cache_paginas_privadas(response):
    if request.endpoint!='static':
        response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma']='no-cache'
        response.headers['Expires']='0'
    return response

@app.route('/login',methods=['GET','POST'])
def login():
    error=None
    if request.method=='GET':
        session.clear()
    if request.method=='POST':
        u=request.form.get('usuario','')
        c=request.form.get('clave','')
        usuario=_authenticate_user(u,c)
        if usuario is not None:
            session.clear()
            session['usuario']=u
            session['idusuario']=int(usuario.get('idusuario',0) or 0)
            session['rol']=str(usuario.get('rol',''))
            csrf_token()
            return redirect('/home')
        error='Usuario o contraseña incorrectos'

    return render_template('login.html', error=error)

@app.route('/logout', methods=['GET','POST'])
def logout():
    session.clear()
    return redirect('/login')

def auth():
    return 'usuario' in session

def es_admin():
    return str(session.get('rol','')).strip().lower()=='administrador'


def formularios_usuario(uid):
    try:
        uf=pd.read_csv('data/usuarios_formularios.csv')
        return {int(x) for x in uf[uf['IdUsuario']==int(uid)]['IdFormulario'].tolist()}
    except Exception:
        return set()


def cotizaciones_por_mes_usuario(path='data/cotizaciones.csv'):
    meses=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
    if not os.path.exists(path):
        return meses,[]
    try:
        cot=pd.read_csv(path,engine='python',on_bad_lines='skip').fillna('')
        if 'fecha' not in cot.columns:
            return meses,[]
        if 'usuario' not in cot.columns:
            cot['usuario']='Sin usuario'
        cot['fecha_dt']=pd.to_datetime(cot['fecha'],errors='coerce')
        cot=cot.dropna(subset=['fecha_dt'])
        cot['mes']=cot['fecha_dt'].dt.month
        cot['usuario']=cot['usuario'].astype(str).str.strip().replace('', 'Sin usuario')
        colores=['#6366F1','#10B981','#F59E0B','#EF4444','#06B6D4','#8B5CF6','#84CC16','#F97316']
        datasets=[]
        for indice,usuario in enumerate(sorted(cot['usuario'].unique().tolist())):
            por_usuario=cot[cot['usuario']==usuario]
            datos=[int((por_usuario['mes']==mes).sum()) for mes in range(1,13)]
            color=colores[indice % len(colores)]
            datasets.append({
                'label':usuario,
                'data':datos,
                'backgroundColor':color,
                'borderColor':color,
                'borderWidth':1,
            })
        return meses,datasets
    except Exception:
        return meses,[]


def puede_usar_formulario(formulario_id):
    return es_admin() or int(formulario_id) in formularios_usuario(session.get('idusuario',0))

def resumen_opciones_pregunta(formulario_id, nombre_pregunta):
    return {}


def pregunta_visible(registro):
    valor=str(registro.get('Visible',1)).strip().lower()
    return valor not in ('0','false','no','inactivo','oculto','invisible')


def formulario_usa_servicios_excel(formulario_id):
    try:
        params=pd.read_csv('data/calculos_parametros.csv').fillna('')
        if not params[
            (params['IdFormulario'].astype(str)==str(formulario_id))
            & (params['Operacion'].astype(str).str.upper()=='SERVICIOS_EXCEL')
        ].empty:
            return True
        variables=pd.read_csv('data/variables.csv').fillna('')
        variables=variables[pd.to_numeric(variables.get('IdFormulario'),errors='coerce')==int(formulario_id)]
        return any(
            str(v.get('Tipo','')).upper()=='CALCULADA'
            and str(v.get('Operacion','')).upper()=='SERVICIOS_EXCEL'
            for _,v in variables.iterrows()
        )
    except Exception:
        return False


def formulario_modo_servicios_excel(formulario_id):
    try:
        formularios=pd.read_csv('data/formularios.csv').fillna('')
        fila=formularios[formularios['IdFormulario'].astype(str)==str(formulario_id)]
        if fila.empty or 'ModoServiciosExcel' not in fila.columns:
            return False
        return int(float(fila.iloc[0].get('ModoServiciosExcel',0) or 0))==1
    except Exception:
        return False


def cargar_catalogo_servicios(formulario_id):
    try:
        tarifas=pd.read_csv('data/servicios_tarifas.csv').fillna('')
        tarifas=tarifas[pd.to_numeric(tarifas['IdFormulario'],errors='coerce')==int(formulario_id)]
    except Exception:
        tarifas=pd.DataFrame(columns=['ProductoServicio','Perfil','SalarioTotal'])
    productos=sorted({reparar_texto_mojibake(p) for p in tarifas['ProductoServicio'].astype(str).unique().tolist()}) if not tarifas.empty else []
    perfiles=[]
    for _,fila in tarifas.sort_values(['ProductoServicio','Perfil']).iterrows():
        perfiles.append({
            'producto':reparar_texto_mojibake(fila.get('ProductoServicio','')),
            'perfil':reparar_texto_mojibake(fila.get('Perfil','')),
            'salario':float(fila.get('SalarioTotal',0) or 0),
        })
    parametros=cargar_parametros_calculo(formulario_id,'SERVICIOS_EXCEL')
    id_disponibilidad=str(parametros.get('DISPONIBILIDAD','2004'))
    try:
        opciones=pd.read_csv('data/opciones.csv').fillna('')
        disponibilidad=opciones[opciones['IdVariable'].astype(str)==id_disponibilidad].to_dict('records')
    except Exception:
        disponibilidad=[]
    if not disponibilidad:
        disponibilidad=[
            {'Opcion':'5X7','Valor':0},
            {'Opcion':'5X8','Valor':0},
            {'Opcion':'7X24','Valor':35},
        ]
    return {
        'productos':productos,
        'perfiles':perfiles,
        'disponibilidades':[
            {'opcion':reparar_texto_mojibake(d.get('Opcion','')), 'valor':float(d.get('Valor',0) or 0)}
            for d in disponibilidad
        ],
    }


def cargar_config_servicios(formulario_id):
    valores={
        'APLICAR_DISPONIBILIDAD':1.0,
    }
    try:
        if os.path.exists('data/calculos_config.csv'):
            cfg=pd.read_csv('data/calculos_config.csv').fillna('')
            cfg=cfg[
                (cfg['IdFormulario'].astype(str)==str(formulario_id))
                & (cfg['Operacion'].astype(str).str.upper()=='SERVICIOS_EXCEL')
            ]
        else:
            cfg=pd.read_csv('data/servicios_config.csv').fillna('')
            cfg=cfg[cfg['IdFormulario'].astype(str)==str(formulario_id)]
        for _,fila in cfg.iterrows():
            parametro=str(fila.get('Parametro','')).strip().upper()
            if parametro:
                valores[parametro]=float(fila.get('Valor',0) or 0)
    except Exception:
        pass
    return valores


def cargar_operaciones_calculadas():
    try:
        return pd.read_csv('data/calculos_operaciones.csv').fillna('')
    except Exception:
        return pd.DataFrame(columns=['Operacion','Titulo','Descripcion','Formula','UsaRangos','UsaParametros','UsaConfiguracion'])


def cargar_def_parametros_calculo(operacion):
    try:
        df=pd.read_csv('data/calculos_parametros_def.csv').fillna('')
        return df[df['Operacion'].astype(str).str.upper()==str(operacion).upper()]
    except Exception:
        return pd.DataFrame(columns=['Operacion','Parametro','Etiqueta','Descripcion','Requerido'])


def cargar_def_config_calculo(operacion):
    try:
        df=pd.read_csv('data/calculos_config_def.csv').fillna('')
        return df[df['Operacion'].astype(str).str.upper()==str(operacion).upper()]
    except Exception:
        return pd.DataFrame(columns=['Operacion','Parametro','Etiqueta','Tipo','ValorDefault','Opciones','Descripcion'])


def cargar_config_calculo(formulario_id, operacion, id_pregunta=None):
    valores={}
    definicion=cargar_def_config_calculo(operacion)
    for _,fila in definicion.iterrows():
        valores[str(fila.get('Parametro','')).upper()]=float(fila.get('ValorDefault',0) or 0)
    try:
        cfg=pd.read_csv('data/calculos_config.csv').fillna('')
        cfg=cfg[
            (cfg['IdFormulario'].astype(str)==str(formulario_id))
            & (cfg['Operacion'].astype(str).str.upper()==str(operacion).upper())
        ]
        if id_pregunta is not None and 'IdPregunta' in cfg.columns:
            exacta=cfg[cfg['IdPregunta'].astype(str)==str(id_pregunta)]
            if not exacta.empty:
                cfg=exacta
            else:
                cfg=cfg[cfg['IdPregunta'].astype(str).isin(('', '0', 'nan'))]
        for _,fila in cfg.iterrows():
            valores[str(fila.get('Parametro','')).upper()]=float(fila.get('Valor',0) or 0)
    except Exception:
        pass
    return valores


def guardar_config_calculo(formulario_id, operacion, valores, id_pregunta=None):
    path='data/calculos_config.csv'
    cfg=pd.read_csv(path).fillna('') if os.path.exists(path) else pd.DataFrame(columns=['IdFormulario','IdPregunta','Operacion','Parametro','Valor'])
    if 'IdPregunta' not in cfg.columns:
        cfg['IdPregunta']=''
    if id_pregunta is None:
        cfg=cfg[~((cfg['IdFormulario'].astype(str)==str(formulario_id)) & (cfg['Operacion'].astype(str).str.upper()==str(operacion).upper()) & (cfg['IdPregunta'].astype(str).isin(('', '0', 'nan'))))]
    else:
        cfg=cfg[~((cfg['IdFormulario'].astype(str)==str(formulario_id)) & (cfg['Operacion'].astype(str).str.upper()==str(operacion).upper()) & (cfg['IdPregunta'].astype(str)==str(id_pregunta)))]
    for parametro,valor in valores.items():
        cfg.loc[len(cfg)]={'IdFormulario':formulario_id,'IdPregunta':id_pregunta or '','Operacion':operacion,'Parametro':parametro,'Valor':valor}
    cfg.to_csv(path,index=False)


def numero_desde_texto(valor, predeterminado=0.0):
    try:
        if valor is None or str(valor).strip()=='':
            return float(predeterminado)
        texto=str(valor).replace('$','').replace(' ','').strip()
        if ',' in texto and '.' in texto:
            texto=texto.replace('.','').replace(',','.')
        elif ',' in texto:
            texto=texto.replace(',','.')
        return float(texto)
    except Exception:
        try:
            return float(valor)
        except Exception:
            return float(predeterminado)


def cargar_operandos_calculo(id_pregunta):
    path='data/calculos_operandos.csv'
    if not os.path.exists(path):
        return pd.DataFrame(columns=['IdPregunta','Orden','IdVariable','Rol'])
    try:
        operandos=pd.read_csv(path).fillna('')
        operandos=operandos[operandos['IdPregunta'].astype(str)==str(id_pregunta)]
        if 'Orden' in operandos.columns:
            operandos['OrdenNum']=pd.to_numeric(operandos['Orden'],errors='coerce').fillna(0)
            operandos=operandos.sort_values('OrdenNum')
        return operandos
    except Exception:
        return pd.DataFrame(columns=['IdPregunta','Orden','IdVariable','Rol'])


def guardar_operandos_calculo(id_pregunta, ids_variables, roles):
    path='data/calculos_operandos.csv'
    actual=pd.read_csv(path).fillna('') if os.path.exists(path) else pd.DataFrame(columns=['IdPregunta','Orden','IdVariable','Rol'])
    actual=actual[actual['IdPregunta'].astype(str)!=str(id_pregunta)]
    nuevos=[]
    orden=1
    for id_variable, rol in zip(ids_variables, roles):
        if str(id_variable).strip()=='':
            continue
        nuevos.append({
            'IdPregunta':int(id_pregunta),
            'Orden':orden,
            'IdVariable':int(float(id_variable)),
            'Rol':str(rol or 'BASE').strip().upper() or 'BASE',
        })
        orden+=1
    if nuevos:
        actual=pd.concat([actual,pd.DataFrame(nuevos)],ignore_index=True)
    actual.to_csv(path,index=False)


def es_parametro_servicios_excel(vid, parametro):
    try:
        params=pd.read_csv('data/calculos_parametros.csv').fillna('')
        return not params[
            (params['Operacion'].astype(str).str.upper()=='SERVICIOS_EXCEL')
            & (params['Parametro'].astype(str).str.upper()==str(parametro).upper())
            & (params['IdVariable'].astype(str)==str(vid))
        ].empty
    except Exception:
        return False


def formulario_id_por_pregunta(vid):
    try:
        variables=pd.read_csv('data/variables.csv').fillna('')
        fila=variables[variables['IdVariable'].astype(str)==str(vid)]
        if not fila.empty:
            return int(float(fila.iloc[0].get('IdFormulario',0) or 0))
    except Exception:
        pass
    try:
        params=pd.read_csv('data/calculos_parametros.csv').fillna('')
        fila=params[params['IdVariable'].astype(str)==str(vid)]
        if not fila.empty:
            return int(float(fila.iloc[0].get('IdFormulario',0) or 0))
    except Exception:
        pass
    return 0


def pregunta_es_calculo_servicios(vid):
    return es_parametro_servicios_excel(vid,'TOTAL_SERVICIO')


def datos_pregunta_calculada(vid):
    try:
        variables=asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
        fila=variables[variables['IdVariable'].astype(str)==str(vid)]
        if not fila.empty:
            row=fila.iloc[0]
            return {
                'id':int(float(row.get('IdVariable',vid) or vid)),
                'formulario_id':int(float(row.get('IdFormulario',0) or 0)),
                'pregunta':str(row.get('Variable','')),
                'tipo':str(row.get('Tipo','')),
                'operacion':str(row.get('Operacion','')),
                'comentarios':comentario_pregunta(row),
            }
    except Exception:
        pass
    return {
        'id':int(vid),
        'formulario_id':formulario_id_por_pregunta(vid),
        'pregunta':'',
        'tipo':'CALCULADA',
        'operacion':'',
        'comentarios':'',
    }


def sincronizar_valor_tarifa_perfil(vid, perfil, valor):
    if not es_parametro_servicios_excel(vid,'PERFIL'):
        return
    path='data/servicios_tarifas.csv'
    if not os.path.exists(path):
        return
    tarifas=pd.read_csv(path).fillna('')
    mask=tarifas['Perfil'].astype(str)==str(perfil)
    if mask.any():
        tarifas.loc[mask,'SalarioTotal']=float(valor)
        tarifas.to_csv(path,index=False)


def normalizar_valor_perfil(vid, valor):
    valor=float(valor or 0)
    if es_parametro_servicios_excel(vid,'PERFIL') and 0 < valor < 1000:
        return valor * 1000000
    return valor


def reparar_texto_mojibake(texto):
    texto=str(texto or '')
    for _ in range(3):
        reparado=texto
        for encoding in ('cp1252','latin1'):
            try:
                candidato=texto.encode(encoding).decode('utf-8')
                if candidato!=texto:
                    reparado=candidato
                    break
            except Exception:
                continue
        if reparado==texto:
            break
        texto=reparado
    correcciones={
        'Operaci?n':'Operación',
        'Administraci?n':'Administración',
        'Cotizaci?n':'Cotización',
        'Configuraci?n':'Configuración',
        'Atenci?n':'Atención',
    }
    for origen,destino in correcciones.items():
        texto=texto.replace(origen,destino)
    return texto


def clave_texto(texto):
    texto=reparar_texto_mojibake(texto)
    texto=unicodedata.normalize('NFKD',texto)
    texto=''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+',' ',texto).strip().upper()


def asegurar_columna_comentarios(df):
    if 'Comentarios' not in df.columns:
        df['Comentarios']=''
    df['Comentarios']=df['Comentarios'].fillna('').astype(str)
    df.loc[df['Comentarios'].str.lower().isin(('nan','none','null')),'Comentarios']=''
    return df


def comentarios_opciones_pregunta(opciones_df, id_variable):
    comentarios={}
    opciones_df=asegurar_columna_comentarios(opciones_df.fillna(''))
    for _,opcion in opciones_df[opciones_df['IdVariable'].astype(str)==str(id_variable)].iterrows():
        comentario=str(opcion.get('Comentarios','')).strip()
        if comentario:
            comentarios[clave_texto(opcion.get('Opcion',''))]=reparar_texto_mojibake(comentario)
    return comentarios


def comentario_pregunta(registro):
    valor=str(registro.get('Comentarios','')).strip()
    if valor.lower() in ('','nan','none','null'):
        return ''
    return reparar_texto_mojibake(valor)


def formato_numero_admin(valor):
    texto=str(valor if valor is not None else '').strip()
    if texto.lower() in ('', 'nan', 'none', 'null'):
        return ''
    try:
        numero=float(texto.replace(',','.'))
        if numero.is_integer():
            return str(int(numero))
        return f'{numero:g}'
    except Exception:
        return texto


def unir_comentarios(*comentarios):
    limpios=[reparar_texto_mojibake(c).strip() for c in comentarios if str(c or '').strip()]
    return '\n\n'.join(limpios)


def valor_tarifa_perfil(formulario_id, producto, perfil):
    parametros=cargar_parametros_calculo(formulario_id,'SERVICIOS_EXCEL')
    id_perfil=str(parametros.get('PERFIL',''))
    try:
        opciones=pd.read_csv('data/opciones.csv').fillna('')
        opciones_filtradas=opciones[opciones['IdVariable'].astype(str)==id_perfil].copy()
        opcion=opciones_filtradas[
            opciones_filtradas['Opcion'].astype(str).map(clave_texto)==clave_texto(perfil)
        ]
        if not opcion.empty and float(opcion.iloc[0].get('Valor',0) or 0)>0:
            return float(opcion.iloc[0].get('Valor',0) or 0)
    except Exception:
        pass
    try:
        tarifas=pd.read_csv('data/servicios_tarifas.csv').fillna('')
        tarifas=tarifas[tarifas['IdFormulario'].astype(str)==str(formulario_id)].copy()
        tarifa=tarifas[
            (tarifas['ProductoServicio'].astype(str).map(clave_texto)==clave_texto(producto))
            & (tarifas['Perfil'].astype(str).map(clave_texto)==clave_texto(perfil))
        ]
        if not tarifa.empty:
            return float(tarifa.iloc[0]['SalarioTotal'])
    except Exception:
        pass
    return 0


def calcular_servicios_excel(formulario_id, servicios):
    if not isinstance(servicios,list):
        servicios=[]
    try:
        tarifas=pd.read_csv('data/servicios_tarifas.csv').fillna('')
        tarifas=tarifas[tarifas['IdFormulario'].astype(str)==str(formulario_id)]
    except Exception:
        tarifas=pd.DataFrame(columns=['ProductoServicio','Perfil','SalarioTotal'])
    parametros=cargar_parametros_calculo(formulario_id,'SERVICIOS_EXCEL')
    id_disponibilidad=str(parametros.get('DISPONIBILIDAD','2004'))
    try:
        opciones=pd.read_csv('data/opciones.csv').fillna('')
        disponibilidades=opciones[opciones['IdVariable'].astype(str)==id_disponibilidad]
    except Exception:
        disponibilidades=pd.DataFrame(columns=['Opcion','Valor'])
    config=cargar_config_servicios(formulario_id)
    aplicar_disponibilidad=int(float(config.get('APLICAR_DISPONIBILIDAD',1) or 0))==1
    items=[]
    subtotal=0
    categorias={}
    detalle=[]
    for indice,servicio in enumerate(servicios, start=1):
        producto=str(servicio.get('producto_servicio','') or servicio.get('producto','')).strip()
        perfil=str(servicio.get('perfil','')).strip()
        disponibilidad=str(servicio.get('disponibilidad','')).strip()
        try:
            porcentaje=float(str(servicio.get('porcentaje',0) or 0).replace(',','.'))
        except Exception:
            porcentaje=0
        if not producto and not perfil and porcentaje==0 and not disponibilidad:
            continue
        if not producto or not perfil or porcentaje<=0:
            continue
        salario=valor_tarifa_perfil(formulario_id, producto, perfil)
        servicio_base=salario*(porcentaje/100)
        recargo_pct=0
        disp=disponibilidades[disponibilidades['Opcion'].astype(str).str.upper()==disponibilidad.upper()]
        if aplicar_disponibilidad and not disp.empty:
            recargo_pct=float(disp.iloc[0].get('Valor',0) or 0)
        recargo=servicio_base*(recargo_pct/100)
        total_linea=servicio_base+recargo
        subtotal+=total_linea
        producto_txt=reparar_texto_mojibake(producto)
        perfil_txt=reparar_texto_mojibake(perfil)
        disponibilidad_txt=reparar_texto_mojibake(disponibilidad or 'Sin disponibilidad')
        respuesta=f"{producto_txt} | {perfil_txt} | {porcentaje:g}% | {disponibilidad_txt}"
        items.append({
            'pregunta':f'Servicio {indice}',
            'respuesta':respuesta,
            'valor':round(total_linea,2),
            'valor_calculado':round(total_linea,2),
            'categoria':'Servicio',
            'salario_base':salario,
            'recargo_disponibilidad':round(recargo,2),
        })
        detalle.append(f"Servicio {indice}: ${total_linea:,.0f}")
        categorias['Servicio']=categorias.get('Servicio',0)+total_linea
    total=aplicar_conceptos_formulario(formulario_id,items)
    return {
        'total_numericos':0,
        'total_opciones':round(subtotal,2),
        'total':round(total,2),
        'detalle':'<br>'.join(detalle),
        'items':items,
        'categorias':categorias_desde_items(items),
        'subtotal_servicios':round(subtotal,2),
        'aplicar_disponibilidad':aplicar_disponibilidad,
    }


def items_visibles_pdf(items):
    visibles=[]
    for item in items:
        respuesta=str(item.get('respuesta','')).strip()
        categoria=str(item.get('categoria','')).strip().lower()
        if respuesta in ('','0','None','null'):
            continue
        if categoria=='configuracion' or respuesta.lower()=='configuracion':
            continue
        visibles.append(item)
    return visibles


def aplicar_conceptos_formulario(formulario_id, items):
    try:
        cfg=pd.read_csv('data/configuracion_formularios.csv').fillna('')
        cfg=cfg[cfg['id_formulario'].astype(str)==str(formulario_id)]
    except Exception:
        cfg=pd.DataFrame()
    conceptos_fijos=[]
    if not cfg.empty:
        for _,c in cfg.iterrows():
            if int(float(c.get('activo',1) or 0))==1 and not str(c.get('tipo','')).upper().startswith('POR'):
                conceptos_fijos.append(c)
    subtotal=0
    for item in items:
        valor_real=float(item.get('valor',0) or 0)
        valor_calculado=valor_real
        for _,c in cfg.iterrows():
            if int(float(c.get('activo',1) or 0))!=1:
                continue
            if str(c.get('tipo','')).upper().startswith('POR'):
                valor_calculado += valor_real * (float(c.get('valor',0) or 0)/100)
        item['valor_calculado']=round(valor_calculado,2)
        subtotal += valor_calculado
    total=subtotal
    if subtotal>0:
        for c in conceptos_fijos:
            valor_fijo=float(c.get('valor',0) or 0)
            total += valor_fijo
            items.append({
                'pregunta':str(c.get('concepto','Concepto fijo')),
                'respuesta':'Valor fijo',
                'valor':valor_fijo,
                'valor_calculado':valor_fijo,
                'categoria':'Configuracion'
            })
    return round(total,2)


def categorias_desde_items(items):
    categorias={}
    for item in items:
        categoria=str(item.get('categoria','General'))
        valor=float(item.get('valor_calculado',item.get('valor',0)) or 0)
        categorias[categoria]=categorias.get(categoria,0)+valor
    return {k:round(v,2) for k,v in categorias.items()}


def valor_respuesta_para_calculo(id_variable, respuestas, opciones):
    clave=str(int(float(id_variable)))
    respuesta=respuestas.get(clave,'')
    if str(respuesta).strip()=='':
        return 0.0
    try:
        coincidencia=opciones[
            (opciones['IdVariable'].astype(str)==clave)
            & (opciones['Opcion'].astype(str).str.strip().str.upper()==str(respuesta).strip().upper())
        ]
        if not coincidencia.empty:
            return numero_desde_texto(coincidencia.iloc[0].get('Valor',0),0)
    except Exception:
        pass
    return numero_desde_texto(respuesta,0)


def ids_operandos_calculados(variables):
    ids=set()
    try:
        for _,v in variables.iterrows():
            if str(v.get('Tipo','')).upper()!='CALCULADA':
                continue
            operacion=str(v.get('Operacion','')).upper()
            if operacion not in ('FIJO','SUMAR','MULTIPLICAR','PORCENTAJE'):
                continue
            operandos=cargar_operandos_calculo(int(float(v.get('IdVariable',0) or 0)))
            for _,op in operandos.iterrows():
                if str(op.get('IdVariable','')).strip():
                    ids.add(str(int(float(op.get('IdVariable')))))
    except Exception:
        pass
    return ids


def calcular_calculada_generica(formulario_id, pregunta, respuestas, opciones):
    vid=int(float(pregunta.get('IdVariable',0) or 0))
    operacion=str(pregunta.get('Operacion','')).upper()
    config=cargar_config_calculo(formulario_id,operacion,vid)
    operandos=cargar_operandos_calculo(vid)
    valores=[]
    bases=[]
    porcentajes=[]
    for _,op in operandos.iterrows():
        id_variable=op.get('IdVariable','')
        if str(id_variable).strip()=='':
            continue
        valor=valor_respuesta_para_calculo(id_variable,respuestas,opciones)
        rol=str(op.get('Rol','BASE')).strip().upper() or 'BASE'
        valores.append(valor)
        if rol=='PORCENTAJE':
            porcentajes.append(valor)
        else:
            bases.append(valor)
    if operacion=='FIJO':
        total=valores[0] if valores else numero_desde_texto(config.get('VALOR_CONSTANTE',0),0)
    elif operacion=='SUMAR':
        total=sum(valores)+numero_desde_texto(config.get('AJUSTE',0),0)
    elif operacion=='MULTIPLICAR':
        if valores:
            total=1
            for valor in valores:
                total*=valor
        else:
            total=0
        total*=numero_desde_texto(config.get('FACTOR',1),1)
    elif operacion=='PORCENTAJE':
        base=sum(bases)
        porcentaje=sum(porcentajes) if porcentajes else numero_desde_texto(config.get('PORCENTAJE_FIJO',0),0)
        total=base*(porcentaje/100)
    else:
        total=0
    return round(total,2)

@app.route('/')
def index():
    return redirect('/login')

@app.route('/home')
@login_required
def home():
    if 'idusuario' not in session:
        return redirect('/login')
    if not auth(): return redirect('/login')
    uid=session.get('idusuario',0)
    uid=session.get('idusuario',0)
    try:
        uf=pd.read_csv('data/usuarios_formularios.csv')
        ids=uf[uf['IdUsuario']==uid]['IdFormulario'].tolist()
        if len(ids)==0:
            return render_template('index.html',preguntas=[],categorias={},formularios=[],sin_formularios=True)
        formularios_menu=pd.read_csv('data/formularios.csv')
        formularios_menu=formularios_menu[formularios_menu['IdFormulario'].isin(ids)]
    except:
        formularios_menu=pd.DataFrame(columns=['IdFormulario','Nombre'])
    variables=asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
    if 'IdFormulario' in variables.columns:
        variables=variables[variables['IdFormulario'].isin(ids)]
    opciones=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv').fillna(''))
    preguntas=[]
    for _,v in variables.iterrows():
        vid=int(v['IdVariable'])
        tipo=str(v.get('Tipo','LISTA')).upper()
        if not pregunta_visible(v) or tipo=='CALCULADA':
            continue
        opts=opciones[opciones['IdVariable']==vid]['Opcion'].astype(str).tolist()
        preguntas.append({'id':vid,'variable':v['Variable'],'tipo':tipo,'opciones':opts,'resumenes':comentarios_opciones_pregunta(opciones,vid),'comentario':comentario_pregunta(v)})
        
    from collections import defaultdict
    categorias=defaultdict(list)
    for p in preguntas:
        row=variables[variables['IdVariable']==p['id']].iloc[0]
        categorias[str(row['Categoria'])].append(p)
    resumenes_preguntas={str(p['id']):p['resumenes'] for p in preguntas if p.get('resumenes')}
    return render_template('index.html',preguntas=preguntas,categorias=dict(categorias),formularios=formularios_menu.to_dict('records'),resumenes_preguntas=resumenes_preguntas)

@app.route('/cotizaciones')
@login_required
def cotizaciones():
    if not auth(): return redirect('/login')
    f='data/cotizaciones.csv'
    if not os.path.exists(f): return '<h3>Sin cotizaciones</h3>'
    df=pd.read_csv(f,engine='python',on_bad_lines='skip')
    tabla=df.to_html(index=False,classes='table table-striped table-hover',border=0)
    return f'''
    <!DOCTYPE html><html><head>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
    body{{background:#f4f7fb;padding:20px}}
    .card{{border:none;border-radius:18px;box-shadow:0 4px 18px rgba(0,0,0,.1)}}
    .table thead{{background:#0b2d5c;color:white}}
    .header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}}
    .logo{{height:70px}}
    </style></head><body>
    <div class="card"><div class="card-body">
    <div class="header">
      <div><img class="logo" src="/static/img/logo_qbitech.png"><h3>Cotizaciones QBITECH</h3></div>
      <div>
      <a class="btn btn-success" href="/exportar_excel">📊 Exportar Excel</a>
      <a class="btn btn-danger" href="/exportar_pdf">📄 Exportar PDF</a>
      </div>
    </div>
    {tabla}
    </div></div></body></html>'''

@app.route('/administracion')
@admin_required
def administracion():
    
    if not auth():
        return redirect('/login')
    if not es_admin():
        return 'Acceso denegado. Solo Administradores.',403
    if not auth(): return redirect('/login')
    usuarios=pd.read_csv('data/usuarios.csv').drop(columns=['Clave','clave'],errors='ignore')
    return usuarios.to_html(index=False)

@app.route('/cuestionario_admin',methods=['GET','POST'])
@admin_required
def cuestionario_admin():
    
    if not auth():
        return redirect('/login')
    if not es_admin():
        return 'Acceso denegado. Solo Administradores.',403
    formulario_id=request.args.get('formulario','')
    vista=request.args.get('vista','dashboard')

    
    f='data/variables.csv'
    df=asegurar_columna_comentarios(pd.read_csv(f).fillna(''))
    if 'Visible' not in df.columns:
        df['Visible']=1
    formularios=pd.read_csv('data/formularios.csv').fillna('').to_dict('records')
    if formulario_id and 'IdFormulario' in df.columns:
        try:
            df=df[df['IdFormulario']==int(formulario_id)]
        except:
            pass
    if request.method=='POST':
        nid=(df['IdVariable'].max()+1) if len(df)>0 else 1
        try:
            factor=float(request.form.get('factor',0) or 0)
        except Exception:
            factor=0
        df.loc[len(df)]={'IdVariable':nid,'IdFormulario':int(request.form.get('formulario_id',0) or 0),'Categoria':request.form['categoria'],'Variable':request.form['variable'],'Tipo':request.form.get('tipo','LISTA'),'Operacion':request.form.get('operacion','FIJO'),'Factor':factor,'Estado':'Activo','Visible':request.form.get('visible',1),'Comentarios':request.form.get('comentarios','')}
        df.to_csv(f,index=False)
        try:
            opf='data/opciones.csv'
            op=pd.read_csv(opf)
            if nid not in op['IdVariable'].tolist():
                op.loc[len(op)]={'IdVariable':nid,'Opcion':'SI','Valor':0}
                op.loc[len(op)]={'IdVariable':nid,'Opcion':'NO','Valor':0}
                op.to_csv(opf,index=False)
        except Exception:
            pass
    rows=''
    for _,r in df.iterrows():
        pid=int(r['IdVariable'])
        tipo=str(r.get('Tipo','LISTA'))
        operacion=str(r.get('Operacion','FIJO'))
        if tipo.upper()=='NUMERO':
            icon=''
        elif tipo.upper()=='CALCULADA':
            icon=f"<button type='button' class='btn btn-info btn-sm btn-opciones' data-url='/calculada_config_admin/{pid}'>Configurar Calculo</button>"
        else:
            icon=f"<button type='button' class='btn btn-info btn-sm btn-opciones' data-id='{pid}' data-tipo='{escape(tipo)}' data-operacion='{escape(operacion)}'>Opciones</button>"
        visible=str(r.get('Visible',1))
        argumentos=','.join((str(pid),json.dumps(str(r.get('Categoria',''))),json.dumps(str(r.get('Variable',''))),json.dumps(tipo),json.dumps(str(r.get('Operacion','FIJO'))),json.dumps(float(r.get('Factor',0) or 0)),json.dumps(visible),json.dumps(str(r.get('Comentarios','')))))
        onclick=escape(f'editar({argumentos})')
        token=escape(csrf_token())
        estado_visible='Visible' if pregunta_visible(r) else 'Invisible'
        rows += f"<tr><td>{pid}</td><td>{escape(str(r.get('Categoria','')))}</td><td>{escape(str(r.get('Variable','')))}</td><td>{escape(tipo)}</td><td>{estado_visible}</td><td>{escape(str(r.get('Comentarios','')))}</td><td><div class='acciones-pregunta'><button class='btn btn-warning btn-sm' onclick='{onclick}'>Editar</button> <form style='display:inline' method='post' action='/pregunta_eliminar/{pid}'><input type='hidden' name='_csrf_token' value='{token}'><button class='btn btn-danger btn-sm'>Eliminar</button></form> {icon}</div></td></tr>"
    tabla=f"<table class='table'><tr><th>ID</th><th>Categoria</th><th>Pregunta</th><th>Tipo</th><th>Visible</th><th>Comentarios</th><th>Acciones</th></tr>{rows}</table>"
    formularios=[]
    try:
        formularios=pd.read_csv('data/formularios.csv').fillna('').to_dict('records')
    except:
        pass
    try:
        usuarios=pd.read_csv('data/usuarios.csv').fillna('')
        usuarios.columns=usuarios.columns.str.strip().str.lower()
        usuarios=usuarios.drop(columns=['clave'],errors='ignore')
        usuarios=usuarios.to_dict('records')
        try:
            uf=pd.read_csv('data/usuarios_formularios.csv').fillna('')
            forms=pd.read_csv('data/formularios.csv').fillna('')
            mapa=dict(zip(forms['IdFormulario'],forms['Nombre']))
            for u in usuarios:
                uid=int(u.get('idusuario',u.get('IdUsuario',0)))
                asign=uf[uf['IdUsuario']==uid]['IdFormulario'].tolist() if len(uf)>0 else []
                u['formularios_txt']=', '.join([str(mapa.get(x,'')) for x in asign])
        except Exception:
            pass
    except:
        usuarios=[]
    tabla_cotizaciones=''
    if vista=='cotizaciones':
        try:
            cot=pd.read_csv('data/cotizaciones.csv',engine='python',on_bad_lines='skip')
            tabla_cotizaciones=cot.to_html(index=False,classes='table table-striped table-hover',border=0)
        except:
            tabla_cotizaciones='<div class="alert alert-info">No existen cotizaciones registradas.</div>'
    def contar_csv(path, **kwargs):
        try:
            if os.path.exists(path):
                return len(pd.read_csv(path, **kwargs))
        except Exception:
            return 0
        return 0

    cotizaciones_labels,cotizaciones_datasets=cotizaciones_por_mes_usuario()
    dashboard={
        'usuarios': contar_csv('data/usuarios.csv'),
        'formularios': contar_csv('data/formularios.csv'),
        'cotizaciones': contar_csv(
            'data/cotizaciones.csv',
            engine='python',
            on_bad_lines='skip'
        ),
        'cotizaciones_labels': cotizaciones_labels,
        'cotizaciones_datasets': cotizaciones_datasets
    }
    rangos_por_pregunta={}
    try:
        rangos_df=pd.read_csv('data/rangos_tickets.csv').fillna('')
        for _,rango in rangos_df.iterrows():
            id_pregunta=str(int(float(rango.get('IdPregunta',0) or 0)))
            rangos_por_pregunta.setdefault(id_pregunta,[]).append({
                'desde':str(rango.get('Desde','')),
                'hasta':str(rango.get('Hasta','')),
                'valor':str(rango.get('Valor','')),
            })
    except Exception:
        rangos_por_pregunta={}
    return render_template(
        'cuestionario_admin.html',
        vista=vista,
        dashboard=dashboard,
        tabla=tabla,
        tabla_cotizaciones=tabla_cotizaciones,
        formulario_id=formulario_id,
        formularios=formularios,
        usuarios=usuarios,
        rangos_por_pregunta=rangos_por_pregunta
    )



@app.route('/pregunta_eliminar/<int:pid>', methods=['POST'])
@admin_required
def pregunta_eliminar(pid):
    if not auth(): return redirect('/login')
    df=asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
    df=df[df['IdVariable']!=pid]
    df.to_csv('data/variables.csv',index=False)
    try:
        op=pd.read_csv('data/opciones.csv')
        op=op[op['IdVariable']!=pid]
        op.to_csv('data/opciones.csv',index=False)
    except: pass
    return jsonify({'ok':True})



@app.route('/opciones_admin/<int:vid>', methods=['GET','POST'])
@admin_required
def opciones_admin(vid):
    if pregunta_es_calculo_servicios(vid):
        fid=formulario_id_por_pregunta(vid)
        return redirect(f'/servicios_config_admin/{fid}')
    nombre_pregunta=f'ID {vid}'
    try:
        variables=asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
        pregunta=variables[variables['IdVariable'].astype(str)==str(vid)]
        if not pregunta.empty:
            nombre_pregunta=reparar_texto_mojibake(str(pregunta.iloc[0].get('Variable','')).strip()) or nombre_pregunta
    except Exception:
        pass
    if request.method=='POST':
        op=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv'))
        valor=normalizar_valor_perfil(vid,float(request.form.get('valor',0) or 0))
        op.loc[len(op)]={'IdVariable':vid,'Opcion':request.form['opcion'],'Valor':valor,'Comentarios':request.form.get('comentarios','')}
        op.to_csv('data/opciones.csv',index=False)
        sincronizar_valor_tarifa_perfil(vid,request.form['opcion'],valor)
    op=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv').fillna(''))
    ops=op[op['IdVariable']==vid]
    rows=''
    for _,r in ops.iterrows():
        opcion_texto=str(r['Opcion'])
        opcion_url=quote(opcion_texto,safe='')
        opcion_html=escape(opcion_texto)
        valor_html=escape(str(r['Valor']))
        comentario_html=escape(str(r.get('Comentarios','')))
        token=escape(csrf_token())
        rows += f"<tr><td>{opcion_html}</td><td>{valor_html}</td><td>{comentario_html}</td><td><form class='row g-2 align-items-start' method='post' action='/opcion_editar/{vid}/{opcion_url}'><input type='hidden' name='_csrf_token' value='{token}'><div class='col-md-3'><input class='form-control' name='opcion' value='{opcion_html}'></div><div class='col-md-2'><input class='form-control' name='valor' value='{valor_html}' type='number' step='any'></div><div class='col-md-5'><textarea class='form-control' name='comentarios' rows='2'>{comentario_html}</textarea></div><div class='col-md-2'><button class='btn btn-upd mb-1'>Actualizar</button></div></form> <form style='display:inline' method='post' action='/opcion_eliminar/{vid}/{opcion_url}' onsubmit=\"return confirm('¿Eliminar esta opción?')\"><input type='hidden' name='_csrf_token' value='{token}'><button class='btn-del'>Eliminar</button></form></td></tr>"
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>
body{{background:#f4f7fb;padding:20px;font-family:Segoe UI}}
.card{{border:none;border-radius:18px;box-shadow:0 10px 30px rgba(0,0,0,.12)}}
.header{{background:#0d6efd;color:#fff;padding:15px 20px;border-radius:18px 18px 0 0;font-size:24px;font-weight:700}}
.table{{background:#fff;border-radius:12px;overflow:hidden;table-layout:fixed;width:100%}}
.table thead th{{background:#0d6efd;color:#fff;border:none}}
.table th:nth-child(1),.table td:nth-child(1){{width:27%}}
.table th:nth-child(2),.table td:nth-child(2){{width:14%}}
.table th:nth-child(3),.table td:nth-child(3){{width:39%}}
.table th:nth-child(4),.table td:nth-child(4){{width:20%}}
.table tbody tr:nth-child(even){{background:#f8fbff}}
.table tbody tr:hover{{background:#eef5ff}}
.btn-add{{background:#0d6efd;color:#fff}}
.btn-upd{{background:#ffc107;border:none;color:#111}}
.btn-del{{background:#dc3545;color:#fff;text-decoration:none;border:none}}
input{{border-radius:8px!important;width:100%}}
textarea{{border-radius:8px!important;width:100%;min-width:0;resize:vertical}}
.acciones-opcion{{display:flex;flex-direction:row;gap:8px;align-items:center;justify-content:flex-start;white-space:nowrap;min-width:220px}}
.acciones-opcion form{{display:inline-flex!important;margin:0;flex:0 0 auto}}
.acciones-opcion button{{width:auto;min-width:96px;padding:8px 10px;border-radius:8px;white-space:nowrap}}
</style></head><body>
<div class='card'>
<div class='header'>Opciones Pregunta: {escape(nombre_pregunta)}</div>
<div class='card-body'>
<form method='post' class='row g-2 mb-3'>
<input type='hidden' name='_csrf_token' value='{escape(csrf_token())}'>
<div class='col'><input class='form-control' name='opcion' placeholder='Respuesta'></div>
<div class='col'><input class='form-control' name='valor' type='number' step='any' placeholder='Valor'></div>
<div class='col-12'><textarea class='form-control' name='comentarios' rows='3' placeholder='Comentarios'></textarea></div>
<div class='col-auto'><button class='btn btn-add'>Agregar</button></div>
</form>
<table class='table table-hover' id='tablaOpciones'><thead><tr><th>Respuesta</th><th>Valor</th><th>Comentarios</th><th>Acción</th></tr></thead><tbody>{rows}</tbody></table>
</div></div>
<script>
document.querySelectorAll('#tablaOpciones tbody tr').forEach(function(row,index){{
    const cells=row.querySelectorAll('td');
    if(cells.length<4) return;
    const form=cells[3].querySelector('form[action*="/opcion_editar/"]');
    if(!form) return;
    if(!form.id) form.id='editar_opcion_'+index;
    const respuesta=form.querySelector('[name="opcion"]');
    const valor=form.querySelector('[name="valor"]');
    const comentarios=form.querySelector('[name="comentarios"]');
    const token=form.querySelector('[name="_csrf_token"]');
    const actualizar=form.querySelector('button');
    const eliminarForm=cells[3].querySelector('form[action*="/opcion_eliminar/"]');
    [respuesta,valor,comentarios].forEach(function(campo){{
        if(campo) campo.setAttribute('form',form.id);
    }});
    if(respuesta) cells[0].replaceChildren(respuesta);
    if(valor) cells[1].replaceChildren(valor);
    if(comentarios) cells[2].replaceChildren(comentarios);
    cells[3].classList.add('acciones-opcion');
    if(actualizar){{
        actualizar.classList.add('btn','btn-upd');
        form.replaceChildren();
        if(token) form.appendChild(token);
        form.appendChild(actualizar);
    }}
    if(eliminarForm){{
        cells[3].replaceChildren(form,eliminarForm);
    }}
}});
</script>
</body></html>"""


@app.route('/calculada_config_admin/<int:vid>')
@admin_required
def calculada_config_admin(vid):
    pregunta=datos_pregunta_calculada(vid)
    operacion=str(pregunta.get('operacion','')).upper()
    operaciones=cargar_operaciones_calculadas()
    op_row=operaciones[operaciones['Operacion'].astype(str).str.upper()==operacion]
    if op_row.empty:
        return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
</head><body class='p-4'><div class='alert alert-warning'>La pregunta calculada {vid} no tiene una operacion definida en calculos_operaciones.csv.</div></body></html>"""
    op=op_row.iloc[0]
    formulario_id=int(pregunta.get('formulario_id',0) or formulario_id_por_pregunta(vid))
    variables=pd.read_csv('data/variables.csv').fillna('')
    variables=variables[variables['IdFormulario'].astype(str)==str(formulario_id)]
    opciones_preguntas=''.join(
        f"<option value='{int(float(v.get('IdVariable',0) or 0))}' {{selected_{int(float(v.get('IdVariable',0) or 0))}}}>{escape(str(v.get('IdVariable','')))} - {escape(str(v.get('Variable','')))} ({escape(str(v.get('Tipo','')))} / {escape(str(v.get('Operacion','')))} )</option>"
        for _,v in variables.iterrows()
    )
    parametros_actuales=cargar_parametros_calculo(formulario_id,operacion,vid)
    defs_param=cargar_def_parametros_calculo(operacion)
    filas_param=''
    for _,defp in defs_param.iterrows():
        parametro=str(defp.get('Parametro','')).upper()
        actual=str(parametros_actuales.get(parametro,''))
        opciones=opciones_preguntas.replace(f"{{selected_{actual}}}","selected")
        opciones=re.sub(r"\s*\{selected_\d+\}", "", opciones)
        requerido='Si' if int(float(defp.get('Requerido',0) or 0))==1 else 'No'
        filas_param += f"<tr><td><b>{escape(str(defp.get('Etiqueta',parametro)))}</b><br><small>{escape(parametro)}</small></td><td>{escape(str(defp.get('Descripcion','')))}</td><td>{requerido}</td><td><select class='form-control' name='param_{escape(parametro)}'><option value=''>Seleccione</option>{opciones}</select></td></tr>"
    defs_cfg=cargar_def_config_calculo(operacion)
    config_actual=cargar_config_calculo(formulario_id,operacion,vid)
    campos_cfg=''
    for _,defc in defs_cfg.iterrows():
        parametro=str(defc.get('Parametro','')).upper()
        etiqueta=escape(str(defc.get('Etiqueta',parametro)))
        tipo=str(defc.get('Tipo','')).upper()
        actual=config_actual.get(parametro,float(defc.get('ValorDefault',0) or 0))
        if tipo=='BOOLEANO':
            si='selected' if int(float(actual or 0))==1 else ''
            no='selected' if int(float(actual or 0))!=1 else ''
            campo=f"<select class='form-control' name='cfg_{escape(parametro)}'><option value='1' {si}>SI</option><option value='0' {no}>NO</option></select>"
        else:
            campo=f"<input class='form-control' name='cfg_{escape(parametro)}' type='number' step='0.01' value='{escape(str(actual))}'>"
        campos_cfg += f"<div class='col-md-4'><label>{etiqueta}</label>{campo}<small>{escape(str(defc.get('Descripcion','')))}</small></div>"
    operandos_html=''
    if int(float(op.get('UsaOperandos',0) or 0))==1:
        operandos=cargar_operandos_calculo(vid)
        def select_pregunta(actual=''):
            opciones=[]
            for _,vp in variables.iterrows():
                idp=str(int(float(vp.get('IdVariable',0) or 0)))
                if idp==str(vid):
                    continue
                selected='selected' if idp==str(actual) else ''
                opciones.append(f"<option value='{idp}' {selected}>{escape(idp)} - {escape(str(vp.get('Variable','')))} ({escape(str(vp.get('Tipo','')))} / {escape(str(vp.get('Operacion','')))})</option>")
            return "<select class='form-control' name='operand_id'><option value=''>Seleccione</option>"+''.join(opciones)+"</select>"
        def select_rol(actual='BASE'):
            actual=str(actual or 'BASE').upper()
            base='selected' if actual!='PORCENTAJE' else ''
            pct='selected' if actual=='PORCENTAJE' else ''
            return f"<select class='form-control' name='operand_rol'><option value='BASE' {base}>BASE</option><option value='PORCENTAJE' {pct}>PORCENTAJE</option></select>"
        filas_operandos=''
        for _,operand in operandos.iterrows():
            filas_operandos += f"<tr><td>{select_pregunta(operand.get('IdVariable',''))}</td><td>{select_rol(operand.get('Rol','BASE'))}</td></tr>"
        filas_operandos += f"<tr><td>{select_pregunta('')}</td><td>{select_rol('BASE')}</td></tr>"
        operandos_html=f"""<hr><h5>Preguntas origen</h5>
<p class='text-muted mb-2'>Agregue una o varias preguntas para que esta calculada las use como operandos. En PORCENTAJE marque como BASE las preguntas que reciben el porcentaje y como PORCENTAJE las preguntas que contienen el porcentaje.</p>
<table class='table'><thead><tr><th>Pregunta origen</th><th>Rol</th></tr></thead><tbody>{filas_operandos}</tbody></table>"""
    rangos_html=''
    if int(float(op.get('UsaRangos',0) or 0))==1:
        try:
            rangos=pd.read_csv('data/rangos_tickets.csv').fillna('')
            rangos=rangos[rangos['IdPregunta'].astype(str)==str(vid)]
        except Exception:
            rangos=pd.DataFrame(columns=['Desde','Hasta','Valor','Comentarios'])
        rangos=asegurar_columna_comentarios(rangos)
        filas=''.join(
            f"<tr><td><input class='form-control' name='desde' value='{escape(formato_numero_admin(r.get('Desde','')))}'></td><td><input class='form-control' name='hasta' value='{escape(formato_numero_admin(r.get('Hasta','')))}'></td><td><input class='form-control' name='valor' value='{escape(formato_numero_admin(r.get('Valor','')))}'></td><td><textarea class='form-control' name='comentario_rango' rows='2'>{escape(str(r.get('Comentarios','')))}</textarea></td></tr>"
            for _,r in rangos.iterrows()
        )
        rangos_html=f"<hr><h5>Rangos</h5><table class='table'><thead><tr><th>Desde</th><th>Hasta</th><th>Valor Base</th><th>Comentario</th></tr></thead><tbody>{filas}<tr><td><input class='form-control' name='desde' placeholder='Desde'></td><td><input class='form-control' name='hasta' placeholder='Hasta'></td><td><input class='form-control' name='valor' placeholder='Valor Base'></td><td><textarea class='form-control' name='comentario_rango' rows='2' placeholder='Comentario'></textarea></td></tr></tbody></table>"
    comentario_actual=escape(comentario_pregunta({'Comentarios':pregunta.get('comentarios','')}))
    token=escape(csrf_token())
    if int(float(op.get('UsaRangos',0) or 0))==1:
        return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>body{{padding:20px;background:#f8fafc;font-family:Segoe UI}} .card{{border:none;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.12)}} .header{{background:#0d6efd;color:#fff;padding:14px 18px;border-radius:16px 16px 0 0;font-weight:700;font-size:22px}}</style>
</head><body><div class='card'><div class='header'>Configurar pregunta calculada {vid}</div><div class='card-body'>
<form method='post' action='/calculada_config_admin/{vid}/guardar'>
<input type='hidden' name='_csrf_token' value='{token}'>
{rangos_html}
<button class='btn btn-primary mt-3'>Guardar Configuración</button>
</form>
</div></div></body></html>"""
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>body{{padding:20px;background:#f8fafc;font-family:Segoe UI}} .card{{border:none;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.12)}} .header{{background:#0d6efd;color:#fff;padding:14px 18px;border-radius:16px 16px 0 0;font-weight:700;font-size:22px}} small{{color:#667085}}</style>
</head><body><div class='card'><div class='header'>Configurar pregunta calculada {vid}</div><div class='card-body'>
<p><b>Pregunta:</b> {escape(pregunta.get('pregunta',''))}</p>
<p><b>Operacion:</b> {escape(operacion)}</p>
<p><b>Logica:</b> {escape(str(op.get('Descripcion','')))}</p>
<p><b>Formula:</b> {escape(str(op.get('Formula','')))}</p>
<form method='post' action='/calculada_config_admin/{vid}/guardar'>
<input type='hidden' name='_csrf_token' value='{token}'>
<div class='mb-3'>
<label><b>Comentarios</b></label>
<textarea class='form-control' name='comentarios' rows='3' placeholder='Comentarios de la pregunta calculada'>{comentario_actual}</textarea>
</div>
<h5>Parametros de entrada y salida</h5>
<table class='table'><thead><tr><th>Parametro</th><th>Uso logico</th><th>Requerido</th><th>Pregunta asociada</th></tr></thead><tbody>{filas_param}</tbody></table>
{('<hr><h5>Configuracion de la operacion</h5><div class=\"row g-2\">'+campos_cfg+'</div>') if campos_cfg else ''}
{operandos_html}
{rangos_html}
<button class='btn btn-primary mt-3'>Guardar Configuracion</button>
</form>
</div></div></body></html>"""


@app.route('/calculada_config_admin/<int:vid>/rangos', methods=['POST'])
@admin_required
def calculada_config_admin_guardar_rangos(vid):
    desde=request.form.getlist('desde')
    hasta=request.form.getlist('hasta')
    valor=request.form.getlist('valor')
    comentarios=request.form.getlist('comentario_rango')
    nuevos=[]
    for d,h,v,c in zip(desde,hasta,valor,comentarios):
        if str(d).strip()=='' or str(h).strip()=='' or str(v).strip()=='':
            continue
        nuevos.append({'IdPregunta':vid,'Desde':float(d),'Hasta':float(h),'Valor':float(v),'Comentarios':str(c or '').strip()})
    path='data/rangos_tickets.csv'
    actual=asegurar_columna_comentarios(pd.read_csv(path).fillna('')) if os.path.exists(path) else pd.DataFrame(columns=['IdPregunta','Desde','Hasta','Valor','Comentarios'])
    actual=actual[actual['IdPregunta'].astype(str)!=str(vid)]
    if nuevos:
        actual=pd.concat([actual,pd.DataFrame(nuevos)],ignore_index=True)
    actual.to_csv(path,index=False)
    return redirect(f'/calculada_config_admin/{vid}')


@app.route('/calculada_config_admin/<int:vid>/guardar', methods=['POST'])
@admin_required
def calculada_config_admin_guardar(vid):
    pregunta=datos_pregunta_calculada(vid)
    operacion=str(pregunta.get('operacion','')).upper()
    formulario_id=int(pregunta.get('formulario_id',0) or formulario_id_por_pregunta(vid))

    variables_path='data/variables.csv'
    variables=asegurar_columna_comentarios(pd.read_csv(variables_path).fillna(''))
    idx=variables[variables['IdVariable'].astype(str)==str(vid)].index
    if len(idx):
        variables.loc[idx[0],'Comentarios']=str(request.form.get('comentarios','')).strip()
        variables.to_csv(variables_path,index=False)

    defs_param=cargar_def_parametros_calculo(operacion)
    params_path='data/calculos_parametros.csv'
    params=pd.read_csv(params_path).fillna('') if os.path.exists(params_path) else pd.DataFrame(columns=['IdFormulario','IdPregunta','Operacion','Parametro','IdVariable'])
    if 'IdPregunta' not in params.columns:
        params['IdPregunta']=''
    param_keys=[f"param_{str(defp.get('Parametro','')).upper()}" for _,defp in defs_param.iterrows()]
    if any(key in request.form for key in param_keys):
        params=params[~((params['IdFormulario'].astype(str)==str(formulario_id)) & (params['Operacion'].astype(str).str.upper()==operacion) & (params['IdPregunta'].astype(str)==str(vid)))]
        for _,defp in defs_param.iterrows():
            parametro=str(defp.get('Parametro','')).upper()
            id_variable=request.form.get(f'param_{parametro}','')
            if str(id_variable).strip():
                params.loc[len(params)]={'IdFormulario':formulario_id,'IdPregunta':vid,'Operacion':operacion,'Parametro':parametro,'IdVariable':int(float(id_variable))}
        params.to_csv(params_path,index=False)

    defs_cfg=cargar_def_config_calculo(operacion)
    valores_cfg={}
    for _,defc in defs_cfg.iterrows():
        parametro=str(defc.get('Parametro','')).upper()
        valores_cfg[parametro]=float(request.form.get(f'cfg_{parametro}',defc.get('ValorDefault',0)) or 0)
    if valores_cfg:
        guardar_config_calculo(formulario_id,operacion,valores_cfg,vid)

    op_row=cargar_operaciones_calculadas()
    op_row=op_row[op_row['Operacion'].astype(str).str.upper()==operacion]
    usa_operandos=not op_row.empty and int(float(op_row.iloc[0].get('UsaOperandos',0) or 0))==1
    if usa_operandos:
        guardar_operandos_calculo(vid,request.form.getlist('operand_id'),request.form.getlist('operand_rol'))
    usa_rangos=not op_row.empty and int(float(op_row.iloc[0].get('UsaRangos',0) or 0))==1
    if usa_rangos:
        desde=request.form.getlist('desde')
        hasta=request.form.getlist('hasta')
        valor=request.form.getlist('valor')
        comentarios=request.form.getlist('comentario_rango')
        nuevos=[]
        for d,h,v,c in zip(desde,hasta,valor,comentarios):
            if str(d).strip()=='' or str(h).strip()=='' or str(v).strip()=='':
                continue
            nuevos.append({'IdPregunta':vid,'Desde':float(d),'Hasta':float(h),'Valor':float(v),'Comentarios':str(c or '').strip()})
        path='data/rangos_tickets.csv'
        actual=asegurar_columna_comentarios(pd.read_csv(path).fillna('')) if os.path.exists(path) else pd.DataFrame(columns=['IdPregunta','Desde','Hasta','Valor','Comentarios'])
        actual=actual[actual['IdPregunta'].astype(str)!=str(vid)]
        if nuevos:
            actual=pd.concat([actual,pd.DataFrame(nuevos)],ignore_index=True)
        actual.to_csv(path,index=False)

    return redirect(f'/calculada_config_admin/{vid}')


@app.route('/servicios_config_admin/<int:fid>', methods=['GET','POST'])
@admin_required
def servicios_config_admin(fid):
    path='data/servicios_config.csv'
    if request.method=='POST':
        cfg=pd.read_csv(path).fillna('') if os.path.exists(path) else pd.DataFrame(columns=['IdFormulario','Parametro','Valor'])
        valor=float(request.form.get('APLICAR_DISPONIBILIDAD',1) or 0)
        mask=(cfg['IdFormulario'].astype(str)==str(fid)) & (cfg['Parametro'].astype(str)=='APLICAR_DISPONIBILIDAD')
        if mask.any():
            cfg.loc[mask,'Valor']=valor
        else:
            cfg.loc[len(cfg)]={'IdFormulario':fid,'Parametro':'APLICAR_DISPONIBILIDAD','Valor':valor}
        cfg.to_csv(path,index=False)

        params_path='data/calculos_parametros.csv'
        params=pd.read_csv(params_path).fillna('')
        if 'IdPregunta' not in params.columns:
            params['IdPregunta']=''
        params=params[~((params['IdFormulario'].astype(str)==str(fid)) & (params['Operacion'].astype(str).str.upper()=='SERVICIOS_EXCEL'))]
        for parametro in ['PRODUCTO_SERVICIO','PERFIL','PORCENTAJE','DISPONIBILIDAD','TOTAL_SERVICIO']:
            id_variable=int(float(request.form.get(parametro,0) or 0))
            params.loc[len(params)]={'IdFormulario':fid,'IdPregunta':int(request.form.get('TOTAL_SERVICIO',0) or 0),'Operacion':'SERVICIOS_EXCEL','Parametro':parametro,'IdVariable':id_variable}
        params.to_csv(params_path,index=False)
    config=cargar_config_servicios(fid)
    params=cargar_parametros_calculo(fid,'SERVICIOS_EXCEL')
    token=escape(csrf_token())
    def input_param(nombre):
        return f"<div class='col-md-4'><label>{escape(nombre)}</label><input class='form-control' name='{escape(nombre)}' type='number' value='{escape(str(params.get(nombre,'')))}'></div>"
    campos=''.join(input_param(nombre) for nombre in ['PRODUCTO_SERVICIO','PERFIL','PORCENTAJE','DISPONIBILIDAD','TOTAL_SERVICIO'])
    aplicar=int(float(config.get('APLICAR_DISPONIBILIDAD',1) or 0))
    seleccionado_si='selected' if aplicar==1 else ''
    seleccionado_no='selected' if aplicar!=1 else ''
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>body{{padding:20px;background:#f8fafc;font-family:Segoe UI}} .card{{border:none;border-radius:16px;box-shadow:0 8px 24px rgba(0,0,0,.12)}} .header{{background:#0d6efd;color:#fff;padding:14px 18px;border-radius:16px 16px 0 0;font-weight:700;font-size:22px}}</style>
</head><body><div class='card'><div class='header'>Configurar Calculo 2005</div><div class='card-body'>
<p><b>Logica:</b> la pregunta 2005 calcula el total de cada servicio usando las respuestas de otras preguntas asociadas por ID.</p>
<p><b>Operacion:</b> SERVICIOS_EXCEL</p>
<p><b>Formula:</b> Total servicio = Valor del Perfil x Porcentaje / 100. Si disponibilidad esta activa, suma recargo de disponibilidad sobre ese subtotal.</p>
<form method='post'>
<input type='hidden' name='_csrf_token' value='{token}'>
<div class='row g-2'>
{campos}
<div class='col-md-4'><label>Aplicar disponibilidad</label><select class='form-control' name='APLICAR_DISPONIBILIDAD'><option value='1' {seleccionado_si}>SI</option><option value='0' {seleccionado_no}>NO</option></select></div>
</div>
<button class='btn btn-primary mt-3'>Guardar Configuracion</button>
</form>
</div></div></body></html>"""


@app.route('/servicios_config_admin_pregunta/<int:vid>')
@admin_required
def servicios_config_admin_pregunta(vid):
    fid=formulario_id_por_pregunta(vid)
    if not fid:
        return 'No se encontro el formulario asociado a esta pregunta.',404
    return redirect(f'/servicios_config_admin/{fid}')


@app.route('/calcular', methods=['POST'])
@login_required
def calcular():
    try:
        return jsonify(calcular_cotizacion(request.json or {}))
    except ValueError as exc:
        return jsonify({'ok':False,'error':str(exc)}),400
    except PermissionError:
        return jsonify({'ok':False,'error':'Acceso denegado al formulario'}),403


def calcular_cotizacion(data):
    respuestas=data.get('respuestas',{})
    try:
        formulario_id=int(data.get('formulario_id',0))
    except (TypeError,ValueError):
        raise ValueError('Formulario inválido')
    if formulario_id<=0:
        raise ValueError('Debe seleccionar un formulario')
    if not puede_usar_formulario(formulario_id):
        raise PermissionError
    if formulario_usa_servicios_excel(formulario_id) and isinstance(data.get('servicios'),list) and len(data.get('servicios',[]))>0:
        return calcular_servicios_excel(formulario_id, data.get('servicios',[]))
    total_opciones=0; total_numericos=0; detalle=[]; items=[]; categorias={}; explicacion_usuario=[]
    opciones=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv').fillna(''))
    uid=session.get('idusuario',0)
    try:
        uf=pd.read_csv('data/usuarios_formularios.csv')
        ids=uf[uf['IdUsuario']==uid]['IdFormulario'].tolist()
        formularios_menu=pd.read_csv('data/formularios.csv')
        formularios_menu=formularios_menu[formularios_menu['IdFormulario'].isin(ids)]
    except:
        formularios_menu=pd.DataFrame(columns=['IdFormulario','Nombre'])
    variables=asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
    if 'IdFormulario' in variables.columns:
        variables=variables[pd.to_numeric(variables['IdFormulario'],errors='coerce')==formulario_id]
    usa_rango_tickets=any(
        str(v.get('Tipo','')).upper()=='CALCULADA' and str(v.get('Operacion','')).upper()=='RANGO_TICKETS'
        for _,v in variables.iterrows()
    )
    parametros_rango=cargar_parametros_calculo(formulario_id,'RANGO_TICKETS') if usa_rango_tickets else {}
    ids_parametros_rango=set(str(v) for v in parametros_rango.values() if str(v).strip())
    ids_operandos_genericos=ids_operandos_calculados(variables)
    for _,v in variables.iterrows():
        vid=str(int(v['IdVariable']))
        tipo_ext=str(v.get('Tipo','LISTA')).upper()
        operacion_ext=str(v.get('Operacion','')).upper()
        if tipo_ext=='CALCULADA' and operacion_ext in ('FIJO','SUMAR','MULTIPLICAR','PORCENTAJE'):
            valor_calc=calcular_calculada_generica(formulario_id,v,respuestas,opciones)
            categoria=str(v.get('Categoria','General'))
            nombre=str(v.get('Variable','Calculo'))
            comentario=comentario_pregunta(v)
            total_opciones+=valor_calc
            detalle.append(f"{nombre}: ${valor_calc:,.0f}")
            items.append({'pregunta':nombre,'respuesta':operacion_ext,'valor':valor_calc,'categoria':categoria,'comentario':comentario})
            categorias[categoria]=categorias.get(categoria,0)+valor_calc
            continue
        if tipo_ext=='CALCULADA' and operacion_ext=='RANGO_TICKETS':
            cantidad_raw=obtener_respuesta_parametro(respuestas,parametros_rango,'CANTIDAD_TICKETS','')
            delegada_raw=obtener_respuesta_parametro(respuestas,parametros_rango,'OPERACION_DELEGADA','')
            if str(cantidad_raw).strip()=='' and str(delegada_raw).strip()=='':
                continue
            cantidad=float(cantidad_raw or 0)
            delegada=float(delegada_raw or 0)
            horario=obtener_respuesta_parametro(respuestas,parametros_rango,'HORARIO_ATENCION','')
            disponibilidad=obtener_respuesta_parametro(respuestas,parametros_rango,'DISPONIBILIDAD','')
            tickets_totales=cantidad+delegada
            valor_unitario,tickets_cotizados=calcular_rango_tickets(
                cantidad,
                delegada,
                horario,
                disponibilidad,
                id_pregunta=vid,
                id_horario=parametros_rango.get('HORARIO_ATENCION'),
                id_disponibilidad=parametros_rango.get('DISPONIBILIDAD')
            )
            detalle_rango=detalle_rango_tickets(
                cantidad,
                delegada,
                horario,
                disponibilidad,
                id_pregunta=vid,
                id_horario=parametros_rango.get('HORARIO_ATENCION'),
                id_disponibilidad=parametros_rango.get('DISPONIBILIDAD')
            )
            valor_calc=tickets_cotizados*valor_unitario
            rango_aplicado=etiqueta_rango_tickets(tickets_totales,vid)
            total_opciones+=valor_calc
            detalle.append(f"Tickets y Operación Delegada ingresados: {tickets_totales:g}<br>Cotización en rango {rango_aplicado}<br>Valor por ticket con características seleccionadas: ${valor_unitario:,.0f}<br>Valor mensual: ${valor_calc:,.0f}")
            categoria=str(v.get('Categoria','General'))
            comentario=comentario_rango_tickets(tickets_totales,vid)
            respuesta_costos=f'{tickets_totales:g}; cotización en rango {rango_aplicado}; valor por ticket con características seleccionadas: ${valor_unitario:,.0f}'
            items.append({'pregunta':'Tickets y Operación Delegada ingresados','respuesta':respuesta_costos,'valor':valor_calc,'categoria':categoria,'comentario':comentario})
            explicacion_usuario.append({
                'tipo':'rango_tickets',
                'titulo':'Cálculo de tickets',
                'tickets_ingresados':detalle_rango['tickets_ingresados'],
                'tickets_cotizados':detalle_rango['tickets_cotizados'],
                'rango':detalle_rango['rango'],
                'valor_base':detalle_rango['valor_base'],
                'valor_unitario':detalle_rango['valor_unitario'],
                'valor_mensual':valor_calc,
                'horario':detalle_rango['horario'],
                'porcentaje_horario':detalle_rango['porcentaje_horario'],
                'disponibilidad':detalle_rango['disponibilidad'],
                'porcentaje_disponibilidad':detalle_rango['porcentaje_disponibilidad'],
                'comentario':comentario
            })
            categorias[categoria]=categorias.get(categoria,0)+valor_calc
            continue
        nombre=str(v['Variable'])
        comentario_base=comentario_pregunta(v)
        tipo=str(v.get('Tipo','LISTA')).upper()
        if (usa_rango_tickets and vid in ids_parametros_rango) or vid in ids_operandos_genericos:
            items.append({'pregunta':nombre,'respuesta':respuestas.get(vid,''),'valor':0,'categoria':str(v.get('Categoria','General')),'comentario':comentario_base})
            continue
        if tipo=='NUMERO':
            valor=float(respuestas.get(vid,0) or 0)
            op=str(v.get('Operacion','FIJO')).upper()
            factor=v.get('Factor',0)
            try:
                factor=0 if pd.isna(factor) else float(factor)
            except: factor=0
            if op in ('FIJO',''):
                res=valor
            elif op=='MULTIPLICAR':
                res=valor*factor
            elif op=='PORCENTAJE':
                res=valor*(factor/100)
            else:
                res=valor+factor
            categoria=str(v.get('Categoria','General'))
            total_numericos+=res; detalle.append(f"{nombre}: ${res:,.0f}"); items.append({'pregunta':nombre,'respuesta':valor,'valor':res,'categoria':categoria,'comentario':comentario_base}); categorias[categoria]=categorias.get(categoria,0)+res
        else:
            resp=str(respuestas.get(vid,''))
            m=opciones[(opciones['IdVariable']==int(vid)) & (opciones['Opcion'].astype(str)==resp)]
            if not m.empty:
                categoria=str(v.get('Categoria','General'))
                val=float(m.iloc[0].get('Valor',0))
                comentario=unir_comentarios(comentario_base,str(m.iloc[0].get('Comentarios','')).strip())
                op=str(v.get('Operacion','FIJO')).upper()
                if op=='PORCENTAJE':
                    base=sum(float(item.get('valor',0) or 0) for item in items)
                    valor_calculado=base*(val/100)
                    total_opciones+=valor_calculado
                    detalle.append(f"{nombre} ({resp}): {val:g}% = ${valor_calculado:,.0f}")
                    items.append({'pregunta':nombre,'respuesta':resp,'valor':valor_calculado,'categoria':categoria,'porcentaje':val,'base_porcentaje':base,'comentario':comentario})
                    categorias[categoria]=categorias.get(categoria,0)+valor_calculado
                else:
                    total_opciones+=val
                    detalle.append(f"{nombre}: ${val:,.0f}")
                    items.append({'pregunta':nombre,'respuesta':resp,'valor':val,'categoria':categoria,'comentario':comentario})
                    categorias[categoria]=categorias.get(categoria,0)+val
    total=aplicar_conceptos_formulario(formulario_id,items)
    return {'total_numericos':total_numericos,'total_opciones':total_opciones,'total':round(total,2),'detalle':'<br>'.join(detalle),'items':items,'categorias':categorias_desde_items(items),'explicacion_usuario':explicacion_usuario}

@app.route('/guardar_cotizacion', methods=['POST'])
@login_required
def guardar_cotizacion():
    try:
        data=calcular_cotizacion(request.json or {})
    except ValueError as exc:
        return jsonify({'ok':False,'error':str(exc)}),400
    except PermissionError:
        return jsonify({'ok':False,'error':'Acceso denegado al formulario'}),403
    archivo='data/cotizaciones.csv'
    registro={
        'fecha':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total':data['total'],
        'usuario':session.get('usuario',''),
        'idusuario':session.get('idusuario',''),
    }
    if os.path.exists(archivo):
        try:
            existente=pd.read_csv(archivo,engine='python',on_bad_lines='skip').fillna('')
        except Exception:
            existente=pd.DataFrame(columns=['fecha','total','usuario','idusuario'])
        for columna in ['fecha','total','usuario','idusuario']:
            if columna not in existente.columns:
                existente[columna]=''
        df=pd.concat([existente[['fecha','total','usuario','idusuario']],pd.DataFrame([registro])],ignore_index=True)
        df.to_csv(archivo,index=False)
    else:
        df=pd.DataFrame([registro])
        df.to_csv(archivo, index=False)
    return jsonify({'success':True,'mensaje':'Cotización guardada correctamente'})

@app.route('/generar_pdf', methods=['POST'])
@login_required
def generar_pdf():
    try:
        d=calcular_cotizacion(request.json or {})
    except ValueError as exc:
        return jsonify({'ok':False,'error':str(exc)}),400
    except PermissionError:
        return jsonify({'ok':False,'error':'Acceso denegado al formulario'}),403
    archivo=io.BytesIO()
    doc=SimpleDocTemplate(archivo)
    st=getSampleStyleSheet()
    elems=[]
    logo='static/img/logo_qbitech.png'
    if os.path.exists(logo):
        elems.append(Image(logo,width=180,height=60))
    elems.append(Paragraph('COTIZACIÓN QBITECH',st['Title']))
    elems.append(Spacer(1,12))
    items=items_visibles_pdf(d.get('items',[]))
    if items:
        elems.append(Paragraph('DETALLE DE LA COTIZACIÓN',st['Heading2']))
        elems.append(Spacer(1,12))
        categorias={}
        for item in items:
            respuesta=str(item.get('respuesta','')).strip()
            cat=reparar_texto_mojibake(item.get('categoria','GENERAL'))
            categorias.setdefault(cat,[]).append(item)

        for cat,lista in categorias.items():
            elems.append(Paragraph(str(escape(cat.upper())),st['Heading2']))
            for item in lista:
                pregunta=reparar_texto_mojibake(item.get('pregunta',''))
                respuesta=reparar_texto_mojibake(item.get('respuesta',''))
                elems.append(Paragraph(f"{escape(pregunta)}: {escape(respuesta)}",st['Normal']))
                comentario=reparar_texto_mojibake(item.get('comentario','')).strip()
                if comentario:
                    comentario_pdf='<br/>'.join(str(escape(linea)) for linea in comentario.splitlines())
                    elems.append(Paragraph(f"<b>Comentario:</b> {comentario_pdf}",st['Normal']))
            elems.append(Spacer(1,8))
    else:
        detalle=str(d.get('detalle',''))
        for linea in detalle.replace('<br>','\n').split('\n'):
            linea=linea.strip()
            if linea:
                linea=reparar_texto_mojibake(linea)
                elems.append(Paragraph(str(escape(linea)),st['Normal']))
    elems.append(Spacer(1,12))
    total=float(d.get('total',0) or 0)
    elems.append(Paragraph(f'TOTAL COTIZACIÓN ANTES DE IVA: ${total:,.0f}',st['Heading2']))
    doc.build(elems)
    archivo.seek(0)
    return send_file(archivo,as_attachment=True,download_name='Cotizacion_QBITECH.pdf',mimetype='application/pdf')



@app.route('/pregunta_editar',methods=['POST'])
@admin_required
def pregunta_editar():
    if not auth(): return redirect('/login')
    df=asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
    if 'Visible' not in df.columns:
        df['Visible']=1
    pid=request.form.get('id','').strip()
    if pid:
        pid=int(pid)
        idx=df[df['IdVariable']==pid].index[0]
        df.loc[idx,'Categoria']=str(request.form['categoria'])
        df.loc[idx,'Variable']=str(request.form['variable'])
        df.loc[idx,'Tipo']=str(request.form.get('tipo','LISTA'))
        df.loc[idx,'Operacion']=str(request.form.get('operacion','FIJO'))
        df.loc[idx,'Comentarios']=str(request.form.get('comentarios',''))
        try:
            df.loc[idx,'Factor']=float(request.form.get('factor',0) or 0)
        except:
            df.loc[idx,'Factor']=0
        df.loc[idx,'Visible']=int(request.form.get('visible',1) or 0)
    else:
        nid=(df['IdVariable'].max()+1) if len(df)>0 else 1
        try:
            factor=float(request.form.get('factor',0) or 0)
        except Exception:
            factor=0
        df.loc[len(df)]={'IdVariable':nid,'IdFormulario':int(request.form.get('formulario_id',0) or 0),'Categoria':request.form['categoria'],'Variable':request.form['variable'],'Tipo':request.form.get('tipo','LISTA'),'Operacion':request.form.get('operacion','FIJO'),'Factor':factor,'Estado':'Activo','Visible':int(request.form.get('visible',1) or 0),'Comentarios':str(request.form.get('comentarios',''))}
    df.to_csv('data/variables.csv',index=False)
    if request.headers.get('X-Requested-With')=='XMLHttpRequest':
        return jsonify({'ok':True,'mensaje':'Pregunta guardada correctamente'})
    return redirect('/cuestionario_admin?vista=preguntas')


from flask import render_template_string

@app.route('/admin_login', methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        u=request.form.get('usuario','')
        c=request.form.get('clave','')
        usuario=_authenticate_user(u,c)
        if usuario is not None:
            session.clear()
            session['usuario']=u
            session['idusuario']=int(usuario.get('idusuario',0) or 0)
            session['rol']=str(usuario.get('rol',''))
            if str(session.get('rol','')).strip().lower()!='administrador':
                session.clear()
                return render_template('admin_login.html', error='Acceso permitido únicamente para Administradores')
            csrf_token()
            return redirect('/cuestionario_admin?vista=dashboard')
        return render_template('admin_login.html', error='Usuario o contraseña incorrectos')
    return render_template('admin_login.html')

@app.route('/usuarios')
@admin_required
def usuarios():
    if not auth(): return redirect('/login')
    usuarios=pd.read_csv('data/usuarios.csv').drop(columns=['Clave','clave'],errors='ignore')
    return usuarios.to_html(index=False)

@app.route('/reportes')
@login_required
def reportes():
    if not auth(): return redirect('/login')
    return '<h2>Reportes Enterprise</h2>'






@app.route('/opcion_eliminar/<int:vid>/<path:opcion>', methods=['POST'])
@admin_required
def opcion_eliminar(vid, opcion):
    op=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv'))
    op=op[~((op['IdVariable']==vid) & (op['Opcion'].astype(str)==opcion))]
    op.to_csv('data/opciones.csv',index=False)
    return redirect(f'/opciones_admin/{vid}')

@app.route('/opcion_editar/<int:vid>/<path:opcion>', methods=['POST'])
@admin_required
def opcion_editar(vid, opcion):
    op=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv'))
    idx=op[(op['IdVariable']==vid) & (op['Opcion'].astype(str)==opcion)].index
    if len(idx):
        valor=normalizar_valor_perfil(vid,float(request.form.get('valor',0) or 0))
        op.loc[idx[0],'Opcion']=request.form['opcion']
        op.loc[idx[0],'Valor']=valor
        op.loc[idx[0],'Comentarios']=request.form.get('comentarios','')
        op.to_csv('data/opciones.csv',index=False)
        sincronizar_valor_tarifa_perfil(vid,request.form['opcion'],valor)
    return redirect(f'/opciones_admin/{vid}')


# moved to end








def cargar_formularios():
    try:
        return pd.read_csv('data/formularios.csv')
    except:
        return pd.DataFrame(columns=['IdFormulario','Nombre'])

@app.route('/formulario/<int:id_formulario>')
@login_required
def formulario(id_formulario):
    if not auth(): return redirect('/login')
    uid=session.get('idusuario',0)
    uid=session.get('idusuario',0)
    try:
        uf=pd.read_csv('data/usuarios_formularios.csv')
        ids=uf[uf['IdUsuario']==uid]['IdFormulario'].tolist()
        formularios_menu=pd.read_csv('data/formularios.csv')
        formularios_menu=formularios_menu[formularios_menu['IdFormulario'].isin(ids)]
    except:
        formularios_menu=pd.DataFrame(columns=['IdFormulario','Nombre'])
    variables=pd.read_csv('data/variables.csv')
    opciones=asegurar_columna_comentarios(pd.read_csv('data/opciones.csv').fillna(''))
    variables=variables[variables['IdFormulario']==id_formulario]
    preguntas=[]
    for _,v in variables.iterrows():
        vid=int(v['IdVariable'])
        tipo=str(v.get('Tipo','LISTA')).upper()
        if not pregunta_visible(v) or tipo=='CALCULADA':
            continue
        opts=opciones[opciones['IdVariable']==vid]['Opcion'].astype(str).tolist()
        preguntas.append({'id':vid,'variable':v['Variable'],'tipo':tipo,'opciones':opts,'resumenes':comentarios_opciones_pregunta(opciones,vid),'comentario':comentario_pregunta(v)})
        
    from collections import defaultdict
    categorias=defaultdict(list)
    for p in preguntas:
        row=variables[variables['IdVariable']==p['id']].iloc[0]
        categorias[str(row['Categoria'])].append(p)
    if not puede_usar_formulario(id_formulario):
        return 'Acceso denegado',403
    formularios=formularios_menu.to_dict('records')
    servicios_excel=formulario_modo_servicios_excel(id_formulario)
    catalogo_servicios=cargar_catalogo_servicios(id_formulario) if servicios_excel else {}
    resumenes_preguntas={str(p['id']):p['resumenes'] for p in preguntas if p.get('resumenes')}
    formulario_nombre=''
    try:
        todos_formularios=pd.read_csv('data/formularios.csv').fillna('')
        fila_form=todos_formularios[todos_formularios['IdFormulario'].astype(str)==str(id_formulario)]
        if not fila_form.empty:
            formulario_nombre=str(fila_form.iloc[0].get('Nombre',''))
    except Exception:
        pass
    return render_template(
        'index.html',
        preguntas=preguntas,
        categorias=dict(categorias),
        formularios=formularios,
        formulario_actual=id_formulario,
        formulario_nombre=formulario_nombre,
        servicios_excel=servicios_excel,
        catalogo_servicios=catalogo_servicios,
        resumenes_preguntas=resumenes_preguntas
    )


@app.route('/formularios')
@admin_required
def formularios_admin():
    try:
        df=pd.read_csv('data/formularios.csv')
        html='<h2>Formularios</h2><a href="/nuevo_formulario">Nuevo Formulario</a><br><br>'+df.to_html(index=False)
        return html
    except Exception as e:
        return str(e)

@app.route('/nuevo_formulario')
@admin_required
def nuevo_formulario():
    return f'''
    <h2>Nuevo Formulario</h2>
    <form method="post" action="/guardar_formulario">
    <input type="hidden" name="_csrf_token" value="{escape(csrf_token())}">
    Nombre:<br><input name="nombre"><br>
    Descripcion:<br><input name="descripcion"><br><br>
    <button type="submit">Guardar</button>
    </form>
    '''

@app.route('/guardar_formulario', methods=['POST'])
@admin_required
def guardar_formulario():
    df=pd.read_csv('data/formularios.csv')
    nid=(df['IdFormulario'].max()+1) if len(df)>0 else 1
    df.loc[len(df)]=[nid,request.form['nombre'],request.form.get('descripcion',''),1]
    df.to_csv('data/formularios.csv',index=False)
    return jsonify({'ok':True})




from flask import jsonify

@app.route('/api/formularios')
@admin_required
def api_formularios():
    import pandas as pd
    return jsonify(pd.read_csv('data/formularios.csv').fillna('').to_dict('records'))



@app.route('/api/formularios/<int:formulario_id>')
@admin_required
def api_formulario(formulario_id):
    import pandas as pd
    df=pd.read_csv('data/formularios.csv').fillna('')
    if 'IdFormulario' in df.columns:
        df=df[df['IdFormulario'].astype(str)==str(formulario_id)]
    return jsonify(df.to_dict('records'))


@app.route('/formulario_crear',methods=['POST'])
@admin_required
def formulario_crear_ajax():
    import pandas as pd
    f='data/formularios.csv'
    df=pd.read_csv(f)
    nombre=request.form.get('nombre','').strip()
    desc=request.form.get('descripcion','').strip()
    if len(nombre)<3:
        return jsonify({'ok':False,'mensaje':'Nombre mínimo 3 caracteres'})
    if not df[df['Nombre'].astype(str).str.upper()==nombre.upper()].empty:
        return jsonify({'ok':False,'mensaje':'Formulario ya existe'})
    nid=(int(df['IdFormulario'].max())+1) if len(df)>0 else 1
    df.loc[len(df)]={'IdFormulario':nid,'Nombre':nombre,'Descripcion':desc,'Activo':1}
    df.to_csv(f,index=False)
    return jsonify({'ok':True})

@app.route('/formulario_eliminar/<int:fid>', methods=['POST'])
@admin_required
def formulario_eliminar_ajax(fid):
    import pandas as pd
    df=pd.read_csv('data/formularios.csv')
    df=df[df['IdFormulario']!=fid]
    df.to_csv('data/formularios.csv',index=False)

    try:
        v=pd.read_csv('data/variables.csv')
        ids=v[v['IdFormulario']==fid]['IdVariable'].tolist() if 'IdFormulario' in v.columns else []
        v=v[v['IdFormulario']!=fid] if 'IdFormulario' in v.columns else v
        v.to_csv('data/variables.csv',index=False)

        o=pd.read_csv('data/opciones.csv')
        if ids:
            o=o[~o['IdVariable'].isin(ids)]
        o.to_csv('data/opciones.csv',index=False)
    except Exception:
        pass

    return jsonify({'ok':True})






@app.route('/usuario_guardar', methods=['POST'])
@admin_required
def usuario_guardar():
    df=pd.read_csv('data/usuarios.csv')
    usuario=request.form.get('usuario','').strip()

    cols=[c.lower() for c in df.columns]
    if 'usuario' in cols:
        col_real=df.columns[cols.index('usuario')]
        if not df[df[col_real].astype(str).str.lower()==usuario.lower()].empty:
            return jsonify({'ok':False,'mensaje':'El usuario ya existe'})

    nid=(df['IdUsuario'].max()+1) if 'IdUsuario' in df.columns and len(df)>0 else len(df)+1
    clave=request.form.get('clave','')
    if len(clave)<8:
        return jsonify({'ok':False,'mensaje':'La clave debe tener al menos 8 caracteres'}),400
    df.loc[len(df)]={'IdUsuario':nid,'Usuario':usuario,'Clave':generate_password_hash(clave),'Nombre':request.form.get('nombre',''),'Rol':request.form.get('rol',''),'IdFormulario':request.form.get('idformulario','1'),'Activo':1}
    df.to_csv('data/usuarios.csv',index=False)
    return jsonify({'ok':True})

@app.route('/usuario_eliminar/<int:uid>', methods=['POST'])
@admin_required
def usuario_eliminar(uid):
    df=pd.read_csv('data/usuarios.csv')
    cols=[c.lower() for c in df.columns]
    id_col='IdUsuario' if 'IdUsuario' in df.columns else df.columns[0]
    user_col=df.columns[cols.index('usuario')] if 'usuario' in cols else df.columns[1]
    usuario=df[df[id_col]==uid]
    if not usuario.empty and str(usuario.iloc[0][user_col]).lower()=='admin':
        return jsonify({'ok':False,'popup':True,'mensaje':'El usuario admin no puede eliminarse'})
    df=df[df[id_col]!=uid]
    df.to_csv('data/usuarios.csv',index=False)
    return jsonify({'ok':True})


@app.route('/api/usuario/<int:uid>')
@admin_required
def api_usuario(uid):
    import pandas as pd
    df=pd.read_csv('data/usuarios.csv').fillna('')
    df.columns=df.columns.str.lower()
    r=df[df['idusuario']==uid]
    r=r.drop(columns=['clave'],errors='ignore')
    return r.to_json(orient='records')

@app.route('/usuario_actualizar',methods=['POST'])
@admin_required
def usuario_actualizar():
    import pandas as pd
    df=pd.read_csv('data/usuarios.csv')
    uid=int(request.form.get('idusuario',0))
    c=df.columns
    idc=c[0]
    df.loc[df[idc]==uid,'Usuario']=request.form.get('usuario','')
    df.loc[df[idc]==uid,'Nombre']=request.form.get('nombre','')
    df.loc[df[idc]==uid,'Rol']=request.form.get('rol','')
    clave=request.form.get('clave','')
    if clave:
        if len(clave)<8:
            return jsonify({'ok':False,'mensaje':'La clave debe tener al menos 8 caracteres'}),400
        clave_col='Clave' if 'Clave' in df.columns else 'clave'
        df.loc[df[idc]==uid,clave_col]=generate_password_hash(clave)
    df.to_csv('data/usuarios.csv',index=False)
    return jsonify({'ok':True})

@app.route('/api/formularios_usuario/<int:uid>')
@admin_required
def api_formularios_usuario(uid):
    import pandas as pd
    try:f=pd.read_csv('data/formularios.csv').fillna('')
    except:return jsonify([])
    try:uf=pd.read_csv('data/usuarios_formularios.csv').fillna('')
    except: uf=pd.DataFrame(columns=['IdUsuario','IdFormulario'])
    asign=set(uf[uf['IdUsuario']==uid]['IdFormulario'].tolist()) if len(uf)>0 else set()
    r=[]
    for _,x in f.iterrows():
        fid=int(x.get('IdFormulario',0))
        r.append({'id':fid,'nombre':str(x.get('Nombre','')),'checked':fid in asign})
    return jsonify(r)


@app.route('/api/formularios_todos')
@admin_required
def api_formularios_todos():
    import pandas as pd
    try:
        df=pd.read_csv('data/formularios.csv').fillna('')
        return df.to_json(orient='records')
    except Exception:
        return '[]'

@app.route('/usuario_formularios_guardar',methods=['POST'])
@admin_required
def usuario_formularios_guardar():
    import pandas as pd
    uid=int(request.form.get('idusuario',0))
    ids=request.form.getlist('formularios')
    f='data/usuarios_formularios.csv'
    try: df=pd.read_csv(f)
    except: df=pd.DataFrame(columns=['IdUsuario','IdFormulario'])
    df=df[df['IdUsuario']!=uid]
    for i in ids: df.loc[len(df)]={'IdUsuario':uid,'IdFormulario':int(i)}
    df.to_csv(f,index=False)
    return jsonify({'ok':True})


@app.route('/api/preguntas/<int:formulario_id>')
@admin_required
def api_preguntas(formulario_id):
    import pandas as pd
    df = asegurar_columna_comentarios(pd.read_csv('data/variables.csv').fillna(''))
    if 'Visible' not in df.columns:
        df['Visible']=1

    if 'IdFormulario' in df.columns:
        df['IdFormulario'] = pd.to_numeric(
            df['IdFormulario'],
            errors='coerce'
        ).fillna(0).astype(int)
        df = df[df['IdFormulario'] == int(formulario_id)]

    columnas = [
        'IdVariable',
        'Categoria',
        'Variable',
        'Tipo',
        'Operacion',
        'Factor',
        'Visible',
        'Comentarios'
    ]

    for c in columnas:
        if c not in df.columns:
            df[c] = ''

    return jsonify(
        df[columnas].fillna('').to_dict(orient='records')
    )


@app.route('/api/conceptos/<int:fid>')
@admin_required
def api_conceptos(fid):
    import pandas as pd
    try:
        df=pd.read_csv('data/configuracion_formularios.csv')
        df=df[df['id_formulario'].astype(str)==str(fid)]
        return jsonify(df.to_dict(orient='records'))
    except Exception:
        return jsonify([])


@app.route('/api/conceptos/eliminar', methods=['POST'])
@admin_required
def api_conceptos_eliminar():
    import pandas as pd
    data=request.get_json()
    fid=data.get('id_formulario')
    concepto=data.get('concepto')
    df=pd.read_csv('data/configuracion_formularios.csv')
    df=df[~((df['id_formulario'].astype(str)==str(fid)) & (df['concepto'].astype(str)==str(concepto)))]
    df.to_csv('data/configuracion_formularios.csv',index=False)
    return jsonify({'ok':True})

@app.route('/api/conceptos/guardar', methods=['POST'])
@admin_required
def api_conceptos_guardar():
    import pandas as pd
    data=request.get_json()
    df=pd.read_csv('data/configuracion_formularios.csv')
    fid=str(data.get('id_formulario'))
    concepto=str(data.get('concepto','')).strip()
    original=str(data.get('concepto_original','')).strip()
    if not fid or fid.lower() in ('none','nan','0'):
        return jsonify({'ok':False,'error':'Debe seleccionar un formulario valido'}),400
    if not concepto:
        return jsonify({'ok':False,'error':'Debe diligenciar el concepto'}),400
    valor=float(data.get('valor',0) or 0)

    if original:
        mask=(df['id_formulario'].astype(str)==fid) & (df['concepto'].astype(str).str.strip()==original)
        if mask.any():
            df.loc[mask,'concepto']=concepto
            df.loc[mask,'tipo']=data.get('tipo')
            df.loc[mask,'valor']=valor
            df.loc[mask,'activo']=int(data.get('activo',1))
            df.to_csv('data/configuracion_formularios.csv',index=False)
            return jsonify({'ok':True,'accion':'actualizado'})

    dup=(df['id_formulario'].astype(str)==fid) & (df['concepto'].astype(str).str.strip().str.upper()==concepto.upper())
    if dup.any():
        return jsonify({'ok':False,'error':'Concepto ya existe'}),409

    df.loc[len(df)]=[int(fid),concepto,data.get('tipo'),valor,int(data.get('activo',1))]
    df.to_csv('data/configuracion_formularios.csv',index=False)
    return jsonify({'ok':True,'accion':'insertado'})

# ===== PREGUNTA CALCULADA: RANGO_TICKETS =====
def cargar_parametros_calculo(formulario_id, operacion, id_pregunta=None):
    try:
        parametros=pd.read_csv('data/calculos_parametros.csv')
        coincidencias=parametros[
            (parametros['IdFormulario'].astype(str)==str(formulario_id)) &
            (parametros['Operacion'].astype(str).str.strip().str.upper()==str(operacion).strip().upper())
        ]
        if id_pregunta is not None and 'IdPregunta' in coincidencias.columns:
            exactas=coincidencias[coincidencias['IdPregunta'].astype(str)==str(id_pregunta)]
            if not exactas.empty:
                coincidencias=exactas
            else:
                coincidencias=coincidencias[coincidencias['IdPregunta'].astype(str).isin(('', '0', 'nan'))]
        return {
            str(row['Parametro']).strip().upper(): str(int(row['IdVariable']))
            for _,row in coincidencias.iterrows()
            if str(row.get('Parametro','')).strip()
        }
    except Exception:
        return {}


def obtener_respuesta_parametro(respuestas, parametros, parametro, predeterminado=''):
    id_variable=str(parametros.get(str(parametro).strip().upper(),'')).strip()
    if id_variable:
        return respuestas.get(id_variable,predeterminado)
    raise ValueError(f'No existe parametrizacion para {parametro}')


def cargar_factor_parametrizado(ruta, opcion, predeterminado=1.0):
    try:
        factores=pd.read_csv(ruta)
        coincidencia=factores[
            factores['Opcion'].astype(str).str.strip().str.upper()==str(opcion).strip().upper()
        ]
        if not coincidencia.empty:
            return float(coincidencia.iloc[0]['Factor'])
    except Exception:
        pass
    return predeterminado


def cargar_factor_porcentaje_opcion(id_variable, opcion, predeterminado=None):
    try:
        opciones=pd.read_csv('data/opciones.csv')
        coincidencia=opciones[
            (opciones['IdVariable'].astype(str)==str(id_variable)) &
            (opciones['Opcion'].astype(str).str.strip().str.upper()==str(opcion).strip().upper())
        ]
        if not coincidencia.empty:
            valor=float(coincidencia.iloc[0].get('Valor',0) or 0)
            return 1 + (valor/100)
    except Exception:
        pass
    return predeterminado


def cargar_porcentaje_opcion(id_variable, opcion, predeterminado=0.0):
    try:
        opciones=pd.read_csv('data/opciones.csv')
        coincidencia=opciones[
            (opciones['IdVariable'].astype(str)==str(id_variable)) &
            (opciones['Opcion'].astype(str).str.strip().str.upper()==str(opcion).strip().upper())
        ]
        if not coincidencia.empty:
            return float(coincidencia.iloc[0].get('Valor',0) or 0)
    except Exception:
        pass
    return predeterminado


def detalle_rango_tickets(cantidad_tickets, operacion_delegada, horario, disponibilidad, id_pregunta, id_horario=None, id_disponibilidad=None):
    total_tickets = float(cantidad_tickets or 0) + float(operacion_delegada or 0)
    valor_base = None
    cantidad_cotizada = total_tickets
    rango_aplicado = 'sin rango configurado'
    try:
        rangos=pd.read_csv('data/rangos_tickets.csv')
        rangos=rangos[rangos['IdPregunta'].astype(str)==str(id_pregunta)]
        rangos['DesdeNum']=pd.to_numeric(rangos['Desde'],errors='coerce')
        rangos['HastaNum']=pd.to_numeric(rangos['Hasta'],errors='coerce')
        coincidencia=rangos[
            (rangos['DesdeNum']<=total_tickets) &
            (rangos['HastaNum']>=total_tickets)
        ]
        if not coincidencia.empty:
            fila=coincidencia.iloc[0]
            valor_base=float(fila['Valor'])
            desde=float(fila.get('DesdeNum',0) or 0)
            hasta=float(fila.get('HastaNum',0) or 0)
            hasta_txt='mayor' if hasta>=999999999 else f'{hasta:g}'
            rango_aplicado=f'{desde:g} a {hasta_txt}'
            if hasta < 999999999:
                cantidad_cotizada=hasta
        elif not rangos.dropna(subset=['DesdeNum','HastaNum']).empty:
            rangos_validos=rangos.dropna(subset=['DesdeNum','HastaNum']).sort_values('HastaNum')
            ultimo=rangos_validos.iloc[-1]
            if total_tickets > float(ultimo['HastaNum']):
                valor_base=float(ultimo['Valor'])
                cantidad_cotizada=total_tickets
                rango_aplicado=f"{float(ultimo.get('DesdeNum',0) or 0):g} en adelante"
    except Exception:
        pass
    if valor_base is None:
        raise ValueError('No existe un rango configurado para la cantidad de tickets')

    porcentaje_horario = cargar_porcentaje_opcion(id_horario, horario, 0.0)
    porcentaje_disp = cargar_porcentaje_opcion(id_disponibilidad, disponibilidad, 0.0)
    if str(horario).strip().upper() == '7*24':
        porcentaje_disp = 0.0

    valor_unitario=round(valor_base * (1 + porcentaje_horario/100) * (1 + porcentaje_disp/100), 2)
    return {
        'tickets_ingresados': total_tickets,
        'tickets_cotizados': cantidad_cotizada,
        'rango': rango_aplicado,
        'valor_base': valor_base,
        'valor_unitario': valor_unitario,
        'horario': horario,
        'porcentaje_horario': porcentaje_horario,
        'disponibilidad': disponibilidad,
        'porcentaje_disponibilidad': porcentaje_disp,
    }


def calcular_rango_tickets(cantidad_tickets, operacion_delegada, horario, disponibilidad, id_pregunta, id_horario=None, id_disponibilidad=None):
    detalle=detalle_rango_tickets(
        cantidad_tickets,
        operacion_delegada,
        horario,
        disponibilidad,
        id_pregunta,
        id_horario,
        id_disponibilidad
    )

    return detalle['valor_unitario'], detalle['tickets_cotizados']


def etiqueta_rango_tickets(total_tickets, id_pregunta):
    try:
        rangos=pd.read_csv('data/rangos_tickets.csv')
        rangos=rangos[rangos['IdPregunta'].astype(str)==str(id_pregunta)]
        rangos['DesdeNum']=pd.to_numeric(rangos['Desde'],errors='coerce')
        rangos['HastaNum']=pd.to_numeric(rangos['Hasta'],errors='coerce')
        coincidencia=rangos[
            (rangos['DesdeNum']<=float(total_tickets or 0)) &
            (rangos['HastaNum']>=float(total_tickets or 0))
        ]
        if not coincidencia.empty:
            fila=coincidencia.iloc[0]
            desde=float(fila.get('DesdeNum',0) or 0)
            hasta=float(fila.get('HastaNum',0) or 0)
            hasta_txt='mayor' if hasta>=999999999 else f'{hasta:g}'
            return f'{desde:g} a {hasta_txt}'
        rangos_validos=rangos.dropna(subset=['DesdeNum','HastaNum']).sort_values('HastaNum')
        if not rangos_validos.empty:
            ultimo=rangos_validos.iloc[-1]
            if float(total_tickets or 0) > float(ultimo.get('HastaNum',0) or 0):
                return f"{float(ultimo.get('DesdeNum',0) or 0):g} en adelante"
    except Exception:
        pass
    return 'sin rango configurado'


def comentario_rango_tickets(total_tickets, id_pregunta):
    try:
        rangos=asegurar_columna_comentarios(pd.read_csv('data/rangos_tickets.csv').fillna(''))
        rangos=rangos[rangos['IdPregunta'].astype(str)==str(id_pregunta)]
        rangos['DesdeNum']=pd.to_numeric(rangos['Desde'],errors='coerce')
        rangos['HastaNum']=pd.to_numeric(rangos['Hasta'],errors='coerce')
        total=float(total_tickets or 0)
        coincidencia=rangos[
            (rangos['DesdeNum']<=total) &
            (rangos['HastaNum']>=total)
        ]
        if coincidencia.empty:
            rangos_validos=rangos.dropna(subset=['DesdeNum','HastaNum']).sort_values('HastaNum')
            if not rangos_validos.empty and total > float(rangos_validos.iloc[-1].get('HastaNum',0) or 0):
                coincidencia=rangos_validos.tail(1)
        if not coincidencia.empty:
            return comentario_pregunta({'Comentarios':coincidencia.iloc[0].get('Comentarios','')})
    except Exception:
        pass
    return ''


@app.route('/api/rangos')
@admin_required
def api_rangos():
    id_pregunta=str(request.args.get('idPregunta','')).strip()
    ruta=os.path.join('data','rangos_tickets.csv')
    if not os.path.exists(ruta):
        return jsonify({'ok':True,'rangos':[]})
    df=asegurar_columna_comentarios(pd.read_csv(ruta).fillna(''))
    if id_pregunta:
        df=df[df['IdPregunta'].astype(str)==id_pregunta]
    rangos=[]
    for _,r in df.iterrows():
        rangos.append({
            'idPregunta':formato_numero_admin(r.get('IdPregunta','')),
            'desde':formato_numero_admin(r.get('Desde','')),
            'hasta':formato_numero_admin(r.get('Hasta','')),
            'valor':formato_numero_admin(r.get('Valor','')),
            'comentarios':str(r.get('Comentarios','')),
        })
    return jsonify({'ok':True,'rangos':rangos})


import csv, os
from flask import request, jsonify

@app.route('/api/rangos/guardar', methods=['POST'])
@admin_required
def api_guardar_rango():
    data=request.json or {}
    ruta=os.path.join('data','rangos_tickets.csv')
    existe=os.path.exists(ruta)
    if existe:
        df=asegurar_columna_comentarios(pd.read_csv(ruta).fillna(''))
    else:
        df=pd.DataFrame(columns=['IdPregunta','Desde','Hasta','Valor','Comentarios'])
    df.loc[len(df)]={
        'IdPregunta':data.get('idPregunta'),
        'Desde':data.get('desde'),
        'Hasta':data.get('hasta'),
        'Valor':data.get('valor'),
        'Comentarios':data.get('comentarios',''),
    }
    df.to_csv(ruta,index=False)
    return jsonify({'ok':True})


@app.route('/api/rangos/guardar_todos', methods=['POST'])
@admin_required
def api_guardar_rangos_todos():
    data=request.json or {}
    id_pregunta=str(data.get('idPregunta','')).strip()
    rangos=data.get('rangos',[])
    if not id_pregunta:
        return jsonify({'ok':False,'error':'Falta IdPregunta'}),400

    ruta=os.path.join('data','rangos_tickets.csv')
    if os.path.exists(ruta):
        df=asegurar_columna_comentarios(pd.read_csv(ruta).fillna(''))
        df=df[df['IdPregunta'].astype(str)!=id_pregunta]
    else:
        df=pd.DataFrame(columns=['IdPregunta','Desde','Hasta','Valor','Comentarios'])

    nuevos=[]
    for r in rangos:
        nuevos.append({
            'IdPregunta':id_pregunta,
            'Desde':r.get('desde',''),
            'Hasta':r.get('hasta',''),
            'Valor':r.get('valor',''),
            'Comentarios':r.get('comentarios',''),
        })
    if nuevos:
        df=pd.concat([df,pd.DataFrame(nuevos)],ignore_index=True)
    df.to_csv(ruta,index=False)
    return jsonify({'ok':True,'rangos':nuevos})


if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
