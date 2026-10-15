# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {'name': 'Mesh Doctor', 'author': 'Ricardo Lugaresi', 'version': (1, 0, 2),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Mesh Doctor',
           'description': 'Analiza el modelo y lo deja perfecto (cerrado, limpio, sin cruces) para imprimir, partir o separar colores',
           'category': 'Mesh'}
import bpy
from . import common, doctor

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


def _model(context):
    try:
        return common.pick_model(context)
    except common.AddonError:
        return None


def _store(p, obj, rep):
    p.checks.clear()
    for c in rep['checks']:
        it = p.checks.add()
        it.label, it.value, it.sev, it.detail = c['label'], str(c['value']), c['sev'], c['detail']
    p.verdict = rep['verdict']
    p.analyzed = obj.name


class MESH_OT_doctor_analyze(bpy.types.Operator):
    """Revisa el modelo: agujeros, normales, piezas sueltas, cruces, paredes finas…"""
    bl_idname = 'mesh.doctor_analyze'; bl_label = 'Analizar'; bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.doctor_props
        try:
            obj = common.pick_model(context)
            rep = doctor.analyze(context, obj, float(p.nozzle), p.model_unit)
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
            obj = common.pick_model(context)
            out, done, secs = doctor.repair(context, obj, p.model_unit, p.drop_specks, p.drop_internal, p.fill,
                                            p.merge_parts, p.max_faces if p.reduce else 0)
            rep = doctor.analyze(context, out, float(p.nozzle), p.model_unit)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        _store(p, out, rep)
        p.done = '\n'.join(done)
        self.report({'INFO'}, f'Reparado en {secs:.0f} s · ' + VERDICT[rep['verdict']][0])
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
            obj = common.pick_model(context)
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


classes = (DoctorCheck, DoctorProps, MESH_OT_doctor_analyze, MESH_OT_doctor_repair, MESH_OT_doctor_remesh, VIEW3D_PT_doctor)


def register():
    bpy.utils.register_class(DoctorCheck)
    common.register_classes(classes[1:], 'doctor_props', DoctorProps)


def unregister():
    common.unregister_classes(classes[1:], 'doctor_props')
    bpy.utils.unregister_class(DoctorCheck)
