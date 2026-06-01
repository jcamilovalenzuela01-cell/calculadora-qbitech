
from flask import Flask, render_template, request, jsonify, session, redirect, send_file
import pandas as pd, os
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet

app=Flask(__name__)
app.secret_key="QBITECH2026"

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        usuarios=pd.read_csv('data/usuarios.csv')
        u=request.form.get('usuario','')
        c=request.form.get('clave','')
        ok=usuarios[(usuarios['usuario']==u)&(usuarios['clave']==c)]
        if not ok.empty:
            session['usuario']=u
            return redirect('/')
        return render_template('login.html',error='Credenciales inválidas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

def auth():
    return 'usuario' in session

@app.route('/')
def index():
    if not auth(): return redirect('/login')
    variables=pd.read_csv('data/variables.csv')
    opciones=pd.read_csv('data/opciones.csv')
    preguntas=[]
    for _,v in variables.iterrows():
        vid=int(v['IdVariable'])
        tipo=str(v.get('Tipo','LISTA')).upper()
        opts=opciones[opciones['IdVariable']==vid]['Opcion'].astype(str).tolist()
        preguntas.append({'id':vid,'variable':v['Variable'],'tipo':tipo,'opciones':opts})
    from collections import defaultdict
    categorias=defaultdict(list)
    for p in preguntas:
        row=variables[variables['IdVariable']==p['id']].iloc[0]
        categorias[str(row['Categoria'])].append(p)
    return render_template('index.html',preguntas=preguntas,categorias=dict(categorias))

@app.route('/cotizaciones')
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
def administracion():
    if not auth(): return redirect('/login')
    return pd.read_csv('data/usuarios.csv').to_html(index=False)

@app.route('/cuestionario_admin',methods=['GET','POST'])
def cuestionario_admin():
    
    f='data/variables.csv'
    df=pd.read_csv(f)
    if request.method=='POST':
        nid=(df['IdVariable'].max()+1) if len(df)>0 else 1
        df.loc[len(df)]={'IdVariable':nid,'Categoria':request.form['categoria'],'Variable':request.form['variable'],'Tipo':request.form.get('tipo','LISTA'),'Operacion':request.form.get('operacion','FIJO'),'Factor':request.form.get('factor',0),'Estado':'Activo'}
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
        return redirect('/cuestionario_admin?admin=1')
    rows=''
    for _,r in df.iterrows():
        tipo=r.get('Tipo','LISTA'); icon='' if str(tipo).upper()=='NUMERO' else f"<button type='button' class='btn btn-info btn-sm btn-opciones' data-id='{r["IdVariable"]}' data-bs-toggle='modal' data-bs-target='#opcionesModal'>⚙️</button>"; rows += f"<tr><td>{r['IdVariable']}</td><td>{r['Categoria']}</td><td>{r['Variable']}</td><td>{r.get('Tipo','')}</td><td><button class='btn btn-warning btn-sm' onclick=\"editar({r['IdVariable']},'{r['Categoria']}','{r['Variable']}','{r.get('Tipo','LISTA')}','{r.get('Operacion','FIJO')}','{r.get('Factor',0)}')\">✏️</button> <a class='btn btn-danger btn-sm' href='/pregunta_eliminar/{r['IdVariable']}'>🗑️</a> {icon}</td></tr>"
    tabla=f"<table class='table'><tr><th>ID</th><th>Categoria</th><th>Pregunta</th><th>Tipo</th><th>Acciones</th></tr>{rows}</table>"
    return render_template('cuestionario_admin.html',tabla=tabla)



@app.route('/pregunta_eliminar/<int:pid>')
def pregunta_eliminar(pid):
    if not auth(): return redirect('/login')
    df=pd.read_csv('data/variables.csv')
    df=df[df['IdVariable']!=pid]
    df.to_csv('data/variables.csv',index=False)
    try:
        op=pd.read_csv('data/opciones.csv')
        op=op[op['IdVariable']!=pid]
        op.to_csv('data/opciones.csv',index=False)
    except: pass
    return redirect('/cuestionario_admin?admin=1')



@app.route('/opciones_admin/<int:vid>', methods=['GET','POST'])
def opciones_admin(vid):
    if request.method=='POST':
        op=pd.read_csv('data/opciones.csv')
        op.loc[len(op)]={'IdVariable':vid,'Opcion':request.form['opcion'],'Valor':float(request.form.get('valor',0) or 0)}
        op.to_csv('data/opciones.csv',index=False)
    op=pd.read_csv('data/opciones.csv')
    ops=op[op['IdVariable']==vid]
    rows=''
    for _,r in ops.iterrows():
        rows += f"<tr><td>{r['Opcion']}</td><td>{r['Valor']}</td><td><form style='display:inline' method='post' action='/opcion_editar/{vid}/{r['Opcion']}'><input name='opcion' value='{r['Opcion']}'><input name='valor' value='{r['Valor']}' type='number'><button class='btn btn-upd'>✏️ Actualizar</button></form> <a href='/opcion_eliminar/{vid}/{r['Opcion']}' class='btn-del'>🗑️ Eliminar</a></td></tr>"
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
<style>
body{{background:#f4f7fb;padding:20px;font-family:Segoe UI}}
.card{{border:none;border-radius:18px;box-shadow:0 10px 30px rgba(0,0,0,.12)}}
.header{{background:#0d6efd;color:#fff;padding:15px 20px;border-radius:18px 18px 0 0;font-size:24px;font-weight:700}}
.table{{background:#fff;border-radius:12px;overflow:hidden}}
.table thead th{{background:#0d6efd;color:#fff;border:none}}
.table tbody tr:nth-child(even){{background:#f8fbff}}
.table tbody tr:hover{{background:#eef5ff}}
.btn-add{{background:#0d6efd;color:#fff}}
.btn-upd{{background:#ffc107;border:none}}
.btn-del{{background:#dc3545;color:#fff;text-decoration:none;padding:6px 12px;border-radius:8px}}
input{{border-radius:8px!important}}
</style></head><body>
<div class='card'>
<div class='header'>⚙️ Opciones {vid}</div>
<div class='card-body'>
<form method='post' class='row g-2 mb-3'>
<div class='col'><input class='form-control' name='opcion' placeholder='Respuesta'></div>
<div class='col'><input class='form-control' name='valor' type='number' placeholder='Valor'></div>
<div class='col-auto'><button class='btn btn-add'>➕ Agregar</button></div>
</form>
<table class='table table-hover'><thead><tr><th>Respuesta</th><th>Valor</th><th>Acciones</th></tr></thead><tbody>{rows}</tbody></table>
</div></div></body></html>"""


@app.route('/calcular', methods=['POST'])
def calcular():
    data=request.json or {}
    respuestas=data.get('respuestas',{})
    total_opciones=0; total_numericos=0; detalle=[]; items=[]; categorias={}
    opciones=pd.read_csv('data/opciones.csv')
    variables=pd.read_csv('data/variables.csv')
    for _,v in variables.iterrows():
        vid=str(int(v['IdVariable']))
        nombre=str(v['Variable'])
        tipo=str(v.get('Tipo','LISTA')).upper()
        if tipo=='NUMERO':
            valor=float(respuestas.get(vid,0) or 0)
            op=str(v.get('Operacion','FIJO')).upper()
            factor=v.get('Factor',0)
            try:
                factor=0 if pd.isna(factor) else float(factor)
            except: factor=0
            res=valor if op in ('FIJO','') else (valor*factor if op=='MULTIPLICAR' else valor+factor)
            total_numericos+=res; detalle.append(f"{nombre}: ${res:,.0f}"); items.append({'pregunta':nombre,'respuesta':valor,'valor':res}); categorias[str(v.get('Categoria','General'))]=categorias.get(str(v.get('Categoria','General')),0)+res
        else:
            resp=str(respuestas.get(vid,''))
            m=opciones[(opciones['IdVariable']==int(vid)) & (opciones['Opcion'].astype(str)==resp)]
            if not m.empty:
                val=float(m.iloc[0].get('Valor',0)); total_opciones+=val; detalle.append(f"{nombre}: ${val:,.0f}"); items.append({'pregunta':nombre,'respuesta':resp,'valor':val}); categorias[str(v.get('Categoria','General'))]=categorias.get(str(v.get('Categoria','General')),0)+val
    total=total_numericos+total_opciones
    return jsonify({'total_numericos':total_numericos,'total_opciones':total_opciones,'total':total,'detalle':'<br>'.join(detalle),'items':items,'categorias':categorias})

@app.route('/guardar_cotizacion', methods=['POST'])
def guardar_cotizacion():
    data=request.json or {}
    archivo='data/cotizaciones.csv'
    registro={'fecha':datetime.now().strftime('%Y-%m-%d %H:%M:%S'), **data}
    df=pd.DataFrame([registro])
    if os.path.exists(archivo):
        df.to_csv(archivo, mode='a', index=False, header=False)
    else:
        df.to_csv(archivo, index=False)
    return jsonify({'success':True,'mensaje':'Cotización guardada correctamente'})

@app.route('/generar_pdf', methods=['POST'])
def generar_pdf():
    archivo='reportes/Cotizacion_QBITECH.pdf'
    os.makedirs('reportes',exist_ok=True)
    doc=SimpleDocTemplate(archivo)
    st=getSampleStyleSheet()
    d=request.json or {}
    elems=[]
    logo='static/img/logo_qbitech.png'
    if os.path.exists(logo):
        elems.append(Image(logo,width=180,height=60))
    elems.append(Paragraph('COTIZACION QBITECH',st['Title']))
    elems.append(Spacer(1,12))
    items=d.get('items',[])
    if items:
        elems.append(Paragraph('DETALLE DE LA COTIZACION',st['Heading2']))
        elems.append(Spacer(1,12))
        for item in items:
            pregunta=str(item.get('pregunta',''))
            respuesta=str(item.get('respuesta',''))
            valor=float(item.get('valor',0) or 0)
            elems.append(Paragraph(f"{pregunta}: {respuesta} - ${valor:,.0f}",st['Normal']))
    else:
        detalle=str(d.get('detalle',''))
        for linea in detalle.replace('<br>','\n').split('\n'):
            linea=linea.strip()
            if linea:
                elems.append(Paragraph(linea,st['Normal']))
    elems.append(Spacer(1,12))
    total=float(d.get('total',0) or 0)
    elems.append(Paragraph(f'TOTAL COTIZACION: ${total:,.0f}',st['Heading2']))
    doc.build(elems)
    return send_file(archivo,as_attachment=True)



@app.route('/pregunta_editar',methods=['POST'])
def pregunta_editar():
    if not auth(): return redirect('/login')
    df=pd.read_csv('data/variables.csv')
    pid=request.form.get('id','').strip()
    if pid:
        pid=int(pid)
        idx=df[df['IdVariable']==pid].index[0]
        df.loc[idx,'Categoria']=str(request.form['categoria'])
        df.loc[idx,'Variable']=str(request.form['variable'])
        df.loc[idx,'Tipo']=str(request.form.get('tipo','LISTA'))
        df.loc[idx,'Operacion']=str(request.form.get('operacion','FIJO'))
        try:
            df.loc[idx,'Factor']=float(request.form.get('factor',0) or 0)
        except:
            df.loc[idx,'Factor']=0
    else:
        nid=(df['IdVariable'].max()+1) if len(df)>0 else 1
        df.loc[len(df)]={'IdVariable':nid,'Categoria':request.form['categoria'],'Variable':request.form['variable'],'Tipo':request.form.get('tipo','LISTA'),'Operacion':request.form.get('operacion','FIJO'),'Factor':request.form.get('factor',0),'Estado':'Activo'}
    df.to_csv('data/variables.csv',index=False)
    return redirect('/cuestionario_admin?admin=1')


from flask import render_template_string

@app.route('/admin_login', methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        u=request.form.get('usuario','')
        c=request.form.get('clave','')
        df=pd.read_csv('data/usuarios.csv')
        ok=df[(df['usuario'].astype(str)==u) & (df['clave'].astype(str)==c)]
        if not ok.empty:
            return redirect('/cuestionario_admin?admin=1')
        return render_template('admin_login.html', error='Usuario o contraseña incorrectos')
    return render_template('admin_login.html')

@app.route('/usuarios')
def usuarios():
    if not auth(): return redirect('/login')
    return pd.read_csv('data/usuarios.csv').to_html(index=False)

@app.route('/reportes')
def reportes():
    if not auth(): return redirect('/login')
    return '<h2>Reportes Enterprise</h2>'






@app.route('/opcion_eliminar/<int:vid>/<opcion>')
def opcion_eliminar(vid, opcion):
    op=pd.read_csv('data/opciones.csv')
    op=op[~((op['IdVariable']==vid) & (op['Opcion'].astype(str)==opcion))]
    op.to_csv('data/opciones.csv',index=False)
    return redirect(f'/opciones_admin/{vid}')

@app.route('/opcion_editar/<int:vid>/<opcion>', methods=['POST'])
def opcion_editar(vid, opcion):
    op=pd.read_csv('data/opciones.csv')
    idx=op[(op['IdVariable']==vid) & (op['Opcion'].astype(str)==opcion)].index
    if len(idx):
        op.loc[idx[0],'Opcion']=request.form['opcion']
        op.loc[idx[0],'Valor']=float(request.form.get('valor',0) or 0)
        op.to_csv('data/opciones.csv',index=False)
    return redirect(f'/opciones_admin/{vid}')


if __name__=='__main__':
    app.run(debug=True)

# TIPO_LISTA_NUMERO_V13: preguntas LISTA usan opciones, NUMERO usan operacion/factor


# V19_DYNAMIC_ENGINE_ENABLED
# Base para cálculo dinámico LISTA / NUMERO


# V21_FIX_FIJO_NAN
# Ajuste solicitado:
# - Operacion FIJO ignora factor
# - NaN debe tratarse como 0
# - Preparación para resumen dinámico

# V37 PDF adjustments
