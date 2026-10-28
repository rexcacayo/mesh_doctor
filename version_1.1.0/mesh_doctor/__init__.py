# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {'name': 'Mesh Doctor', 'author': 'Ricardo Lugaresi', 'version': (1, 1, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Mesh Doctor',
           'description': 'Analiza el modelo y lo deja perfecto (cerrado, limpio, sin cruces) para imprimir, partir o separar colores',
           'category': 'Mesh'}
import bpy
from . import common, decimate, doctor

SEV_ICON = {'ok': 'CHECKMARK', 'warn': 'ERROR', 'bad': 'CANCEL'}
VERDICT = {'ok': ('Perfecto: listo para imprimir', 'CHECKMARK'),
           'warn': ('Se puede imprimir, pero conviene repararlo', 'ERROR'),
           'bad': ('Hay que repararlo antes de imprimir', 'CANCEL')}


class DoctorCheck(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()
    value: bpy.props.StringProperty()
    sev: bpy.props.StringProperty()
    detail: bpy.props.StringProperty()


class DoctorProps(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades', items=common.UNIT_ITEMS, default='AUTO')
    nozzle: bpy.props.EnumProperty(name='Boquilla', items=[('0.25', '0.25', ''), ('0.4', '0.4', ''), ('0.6', '0.6', ''), ('0.8', '0.8', '')], default='0.4')
    checks: bpy.props.CollectionProperty(type=DoctorCheck)
    verdict: bpy.props.StringProperty(default='')
    analyzed: bpy.props.StringProperty(default='')
    report: bpy.props.StringProperty(default='')
    done: bpy.props.StringProperty(default='')
    drop_specks: bpy.props.BoolProperty(name='Quitar motas y trocitos sueltos', default=True)
    drop_internal: bpy.props.BoolProperty(name='Quitar capas internas', default=True)
    fill: bpy.props.BoolProperty(name='Cerrar agujeros', default=True)
    merge_parts: bpy.props.BoolProperty(name='Unir piezas solapadas', default=True)
    reduce: bpy.props.BoolProperty(name='Reducir caras si pasa de', default=False)
    max_faces: bpy.props.IntProperty(name='Máximo de caras', default=1_000_000, min=10_000, soft_max=5_000_000)
    voxel_mm: bpy.props.FloatProperty(name='Detalle (mm)', description='Tamaño del vóxel: más pequeño = más detalle y más caras. 0 = automático', default=0.0, min=0.0, max=2, precision=2)
    show_opts: bpy.props.BoolProperty(name='Qué hacer', default=False)
    show_rescue: bpy.props.BoolProperty(name='Rescate: rehacer el sólido', default=False)
    kind: bpy.props.EnumProperty(name='Tipo de pieza', items=decimate.KIND_ITEMS, default='SMOOTH')
    dec_report: bpy.props.StringProperty(default='')


def _model(context):
    try:
        return _models(context)[0]
    except common.AddonError:
        return None


def _store(p, obj, rep):
    p.checks.clear()
    for c in rep['checks']:
        it = p.checks.add()
        it.label, it.value, it.sev, it.detail = c['label'], str(c['value']), c['sev'], c['detail']
    p.verdict = rep['verdict']
    p.analyzed = obj.name


def _is_model(obj):
    """Malla del usuario: ni ayudantes de corte ni el estudio de Showcase (suelo, luces, marca)."""
    return obj is not None and obj.type == 'MESH' and not common.is_helper(obj) and not obj.get('showcase')


def _models(context):
    """Modelos con los que trabajar: el activo primero y luego el resto de seleccionados."""
    seen, out = set(), []
    for obj in [context.active_object] + list(context.selected_objects):
        if _is_model(obj) and obj.name not in seen and obj.visible_get():
            seen.add(obj.name); out.append(obj)
    if not out:
        raise common.AddonError('Selecciona tu modelo. El suelo, las luces y la cámara del estudio '
                                'de Showcase no se reparan.')
    return out


class MESH_OT_doctor_analyze(bpy.types.Operator):
    """Revisa el modelo: agujeros, normales, piezas sueltas, cruces, paredes finas…"""
    bl_idname = 'mesh.doctor_analyze'; bl_label = 'Analizar'; bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.doctor_props
        try:
            obj = _models(context)[0]
            rep = doctor.analyze(context, obj, float(p.nozzle), p.model_unit, kind=p.kind)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        _store(p, obj, rep)
        p.done = ''
        self.report({'INFO'}, VERDICT[rep['verdict']][0])
        return {'FINISHED'}


class MESH_OT_doctor_repair(bpy.types.Operator):
    """Arregla todo lo que se pueda y deja una copia lista; el original queda oculto"""
    bl_idname = 'mesh.doctor_repair'; bl_label = 'Dejar perfecto'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.doctor_props
        try:
            models = _models(context)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        outs, notes, skipped, total = [], [], [], 0.0
        for obj in models:          # varias piezas seleccionadas: se reparan todas, una a una
            try:
                out, done, secs = doctor.repair(context, obj, p.model_unit, p.drop_specks, p.drop_internal, p.fill,
                                                p.merge_parts, p.max_faces if p.reduce else 0)
            except common.AddonError as exc:
                skipped.append(f'{obj.name}: {exc}')
                continue
            outs.append(out); total += secs
            notes += ([f'— {obj.name}'] if len(models) > 1 else []) + done
        if not outs:
            self.report({'ERROR'}, skipped[0] if skipped else 'No se pudo reparar.'); return {'CANCELLED'}
        rep = doctor.analyze(context, outs[-1], float(p.nozzle), p.model_unit)
        _store(p, outs[-1], rep)
        for o in context.selected_objects:
            o.select_set(False)
        for o in outs:
            o.select_set(True)
        context.view_layer.objects.active = outs[-1]
        p.done = '\n'.join(notes + [f'sin reparar: {t}' for t in skipped])
        head = f'{len(outs)} piezas reparadas' if len(outs) > 1 else 'Reparado'
        tail = f' · {len(skipped)} sin reparar' if skipped else ''
        self.report({'INFO'}, f'{head} en {total:.0f} s{tail} · ' + VERDICT[rep['verdict']][0])
        return {'FINISHED'}


class MESH_OT_doctor_remesh(bpy.types.Operator):
    """Rehace el sólido entero con vóxeles: siempre sale cerrado y sin cruces (conserva los colores)"""
    bl_idname = 'mesh.doctor_remesh'; bl_label = 'Rehacer sólido'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.doctor_props
        try:
            obj = _models(context)[0]
            notes = []
            cap = min(1_500_000, max(300_000, 2 * len(obj.data.polygons)))   # sin disparar las caras
            out = doctor.remesh_solid(context, obj, p.voxel_mm, p.model_unit, cap, report=notes)
            rep = doctor.analyze(context, out, float(p.nozzle), p.model_unit)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        _store(p, out, rep)
        p.done = '\n'.join(notes)
        self.report({'INFO'}, VERDICT[rep['verdict']][0])
        return {'FINISHED'}


class MESH_OT_doctor_smart_decimate(bpy.types.Operator):
    """Quita caras sin perder forma: diezma por pasos y se queda con el último que cumple la desviación de tu boquilla"""
    bl_idname = 'mesh.doctor_smart_decimate'; bl_label = 'Diezmar inteligente'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.doctor_props
        try:
            obj = _models(context)[0]
            out, info = decimate.smart_decimate(context, obj, float(p.nozzle), p.kind, p.model_unit)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        p.dec_report = '\n'.join(decimate.summary_lines(info))
        if out is None:
            self.report({'INFO'}, info['notes'][0] if info['notes'] else 'Sin cambios')
            return {'FINISHED'}
        rep = doctor.analyze(context, out, float(p.nozzle), p.model_unit, kind=p.kind)
        _store(p, out, rep)
        self.report({'INFO'}, decimate.summary_lines(info)[0])
        return {'FINISHED'}


class MESH_OT_doctor_heatmap(bpy.types.Operator):
    """Pinta en la vista dónde se ha perdido forma al diezmar (verde = nada, rojo = en el límite de tu boquilla)"""
    bl_idname = 'mesh.doctor_heatmap'; bl_label = 'Ver mapa de desviación'; bl_options = {'REGISTER'}

    def execute(self, context):
        sh = context.space_data.shading if context.space_data and context.space_data.type == 'VIEW_3D' else None
        if sh is None:
            return {'CANCELLED'}
        if sh.type == 'SOLID' and sh.color_type == 'VERTEX':
            sh.color_type = 'MATERIAL'
        else:
            sh.type = 'SOLID'
            sh.color_type = 'VERTEX'
        return {'FINISHED'}


class VIEW3D_PT_doctor(bpy.types.Panel):
    bl_label = 'Mesh Doctor'; bl_idname = 'VIEW3D_PT_doctor'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Mesh Doctor'

    def draw(self, context):
        layout = self.layout; p = context.scene.doctor_props
        if common.draw_mode_warning(layout, context):
            return
        model = _model(context)
        box = layout.box()
        box.label(text='1 · Modelo', icon='MESH_DATA')
        if model is None:
            row = box.row(); row.alert = True
            row.label(text='Selecciona el modelo', icon='ERROR')
        else:
            box.label(text=model.name, icon='OBJECT_DATA')
        row = box.row(align=True)
        row.label(text='Boquilla')
        row.prop(p, 'nozzle', expand=True)
        box.prop(p, 'kind', text='Tipo')
        col = box.column(); col.scale_y = 1.4
        col.operator('mesh.doctor_analyze', icon='VIEWZOOM')

        if p.checks:
            box = layout.box()
            text, icon = VERDICT.get(p.verdict, ('', 'INFO'))
            row = box.row(); row.alert = p.verdict == 'bad'
            row.label(text=text, icon=icon)
            box.label(text=p.analyzed, icon='OBJECT_DATA')
            for c in p.checks:
                r = box.row(align=True)
                r.alert = c.sev == 'bad'
                r.label(text=c.label, icon=SEV_ICON.get(c.sev, 'DOT'))
                r.label(text=c.value)
                if c.detail and c.sev != 'ok':
                    s = box.row(); s.scale_y = .7
                    s.label(text='      ' + c.detail)
        if p.done:
            box = layout.box()
            box.label(text='Hecho', icon='CHECKMARK')
            col = box.column(align=True); col.scale_y = .8
            for line in p.done.split('\n'):
                col.label(text='· ' + line)

        box = layout.box()
        box.label(text='2 · Reparar', icon='TOOL_SETTINGS')
        col = box.column(); col.scale_y = 1.6
        col.operator('mesh.doctor_repair', icon='SHADERFX')
        sub = box.column()
        sub.prop(p, 'show_opts', icon='TRIA_DOWN' if p.show_opts else 'TRIA_RIGHT', emboss=False)
        if p.show_opts:
            sub.prop(p, 'drop_specks'); sub.prop(p, 'drop_internal'); sub.prop(p, 'fill'); sub.prop(p, 'merge_parts')
            r = sub.row(align=True); r.prop(p, 'reduce', text='Reducir caras'); r2 = r.row(); r2.enabled = p.reduce; r2.prop(p, 'max_faces', text='')
            sub.prop(p, 'model_unit')
        sub = box.column()
        sub.prop(p, 'show_rescue', icon='TRIA_DOWN' if p.show_rescue else 'TRIA_RIGHT', emboss=False)
        if p.show_rescue:
            t = sub.column(align=True); t.scale_y = .8
            t.label(text='«Dejar perfecto» ya lo usa solo si hace falta.')
            t.label(text='Aquí puedes forzarlo y elegir el detalle.')
            sub.prop(p, 'voxel_mm')
            sub.operator('mesh.doctor_remesh', icon='MOD_REMESH')

        box = layout.box()
        box.label(text='3 · Diezmar inteligente', icon='MOD_DECIM')
        t = box.column(align=True); t.scale_y = .8
        t.label(text='Quita caras sin pasar de la desviación')
        t.label(text='de tu boquilla (0,4 → 0,05 mm). Boquilla y tipo: arriba.')
        col = box.column(); col.scale_y = 1.4
        col.operator('mesh.doctor_smart_decimate', icon='MOD_DECIM')
        if p.dec_report:
            c2 = box.column(align=True); c2.scale_y = .8
            for line in p.dec_report.split('\n'):
                c2.label(text='· ' + line)
            if model is not None and decimate.HEAT_ATTR in getattr(model.data, 'color_attributes', {}):
                box.operator('mesh.doctor_heatmap', icon='COLOR')


classes = (DoctorCheck, DoctorProps, MESH_OT_doctor_analyze, MESH_OT_doctor_repair, MESH_OT_doctor_remesh,
           MESH_OT_doctor_smart_decimate, MESH_OT_doctor_heatmap, VIEW3D_PT_doctor)


def register():
    bpy.utils.register_class(DoctorCheck)
    common.register_classes(classes[1:], 'doctor_props', DoctorProps)


def unregister():
    common.unregister_classes(classes[1:], 'doctor_props')
    bpy.utils.unregister_class(DoctorCheck)
