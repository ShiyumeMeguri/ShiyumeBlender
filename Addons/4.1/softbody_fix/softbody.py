import bmesh
import typing
import bpy
from bpy.types import Context

def Arm_Obj(self,object):
    return object.type == 'ARMATURE'

def softbody_RNA():
    bpy.types.Scene.is_postion=bpy.props.BoolProperty(name='坐标回中心? ',default=True) #设置RNA属性,绑定线段的时候坐标自身回0
    bpy.types.Scene.R_moni=bpy.props.FloatProperty(name='摩擦力:',max=50.0,min=0,default=15.0)
    bpy.types.Scene.R_zhi=bpy.props.FloatProperty(name='反应力:',min=0,default=0.2)
    bpy.types.Scene.R_pos=bpy.props.FloatProperty(name='外部范围:',min=0.01,max=1.0,default=0.95)
    bpy.types.Scene.R_Zuni=bpy.props.FloatProperty(name='阻力:',min=0,max=1.0,default=0.1)
    bpy.types.Scene.R_Juli=bpy.props.FloatProperty(name='距离:',min=0.01,max=1.0,default=0.12)
    bpy.types.Scene.is_bone_Re=bpy.props.BoolProperty(name='重置',default=False) #判断是否重置骨骼参数
    bpy.types.Scene.is_obj_Re=bpy.props.BoolProperty(name='重置',default=False)  #判断是否重置碰撞体参数
    bpy.types.Scene.star_bake=bpy.props.IntProperty(name='烘焙起始帧:',min=0,default=0) #烘焙起始帧
    bpy.types.Scene.stop_bake=bpy.props.IntProperty(name='烘焙结束帧:',min=0,default=250) #烘焙结束帧
    bpy.types.Scene.is_bake=bpy.props.BoolProperty(name='选择烘焙',default=False) #选择烘焙的状态
    bpy.types.Scene.arm_obj_point=bpy.props.PointerProperty(name='选定的骨架',type=bpy.types.Object,poll=Arm_Obj)
    bpy.types.Scene.is_location=bpy.props.BoolProperty(name='骨架归0',default=True) #初始化骨架设置回0

def remove_softbody_RNA():
    del bpy.types.Scene.is_postion
    del bpy.types.Scene.R_moni
    del bpy.types.Scene.R_zhi
    del bpy.types.Scene.R_pos
    del bpy.types.Scene.R_Zuni
    del bpy.types.Scene.R_Juli
    del bpy.types.Scene.is_bone_Re
    del bpy.types.Scene.is_obj_Re
    del bpy.types.Scene.star_bake
    del bpy.types.Scene.stop_bake
    del bpy.types.Scene.is_bake
    del bpy.types.Scene.arm_obj_point
    del bpy.types.Scene.is_location

class SpaceandPanalsetting: #pt相同项继承父类（用于把面板放在什么地方,什么模式下）
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='覆Arm工具'
    
class UI_PT_Father_panel(SpaceandPanalsetting,bpy.types.Panel):
    bl_idname='UI_PT_Father_panel'
    bl_label='实用动画&绑定工具'
    def draw(self, context):
        pass
    
#绘制Ui,按钮启动OPerator
class UI_PT_Bone(SpaceandPanalsetting,bpy.types.Panel):
    bl_idname='UI_PT_Bone'
    bl_label='模拟软体动骨的生成【优化版】'

    def draw(self, context):
        layout=self.layout
        scene=context.scene

        row=layout.row()
        row.label(text='1:添加/删除',icon='LINKED') 
        row.prop(scene,'is_location',text='骨骼坐标回0(默认)')
        row=layout.row()
        row.prop(scene,'arm_obj_point',text='选定的骨架')
        row=layout.row()
        row.operator('bone.name',text='[激活]生成控制线',icon='RNA')
        row=layout.row()
        row.operator('del.obj',text='[激活]一键删除',icon='TRASH')

        

        row=layout.row()
        row.label(text='2:绑定Skin',icon='OUTLINER_OB_ARMATURE')
        row_cul=layout.row()
        row_cul.operator('skin.obj',text='一键绑定',icon='CONSTRAINT_BONE')
        row=layout.row()
        row.label(text='3:追踪/软体[播放查看效果]',icon='DRIVER')
        row=layout.row()
        row.operator('setting.bone',text='一键[追踪+软体]',icon='MOD_SOFT')
        sp=layout.split()
        sp=sp.box()
        sp2=sp.column()
        sp2.prop(scene,'R_moni',text='回弹率:')
        sp2.prop(scene,'R_zhi',text='重力影响:')
        sp4=sp.column()
        sp4.operator('setting.mod',text='修改&重置骨骼参数',icon='ANIM')
        sp4.prop(scene,'is_bone_Re',text='重置[修改需关闭]')
        
        

        row=layout.row()
        row.label(text='4:碰撞体',icon='CON_FOLLOWPATH')
        box4=layout.row()
        box4.operator('setting.objects',text='[选中]添加/删除',icon='MOD_MASK')
        box=layout.split()
        box=box.box()
        sp_32=box.column()
        sp_32.prop(scene,'R_Zuni',text='摩擦力:')
        sp_32.prop(scene,'R_pos',text='距离:')
        sp_32.prop(scene,'R_Juli',text='范围:')
        sp_4=box.column()
        sp_4.operator('setting.colln',text='修改&重置碰撞参数',icon='ANIM')
        sp_4.prop(scene,'is_obj_Re',text='重置[修改需关闭]')

        new_box=layout.box()
        row1=new_box
        row1.label(text='烘焙碰撞体',icon='PREVIEW_RANGE')
        row1.prop(scene,'star_bake',text='起始关键帧:')
        row1.prop(scene,'stop_bake',text='结束关键帧:')
        cul_box=row1.row()
        cul_box.prop(scene,'is_bake',text='删除烘焙?[非默认]')
        cul_box.operator('setting.bake',text='烘焙&删除【碰撞体】',icon='PINNED')
   
class UI_PT_Explain(SpaceandPanalsetting,bpy.types.Panel):  #解释具体用法

    bl_label='疑问&操作手册'
    bl_parent_id='UI_PT_Bone'

    def draw(self, context):
        scene=context.scene
        layout=self.layout

        row=layout.column()
        row=row.box()
        row=row.column()
        row.label(text='作者:覆Fu ')
        row.label(text='Q:146290608')
        row.label(text='该版本为Blender3.3.1开发/另外版本可能会有无法使用的bug')
        row=layout.column()

        row.label(text='注意事项:')
        row.label(text='Warning_1:该插件原理来自b站,有自身的局限性',icon='PLUS')
        row.label(text='                若要制作mmd,加动骨前不要添加vmd文件')
        row.label(text='                并且该插件目前没有功能: 关键帧开关物理[之后可能添加]')
        row.label(text='')
        row.label(text='warning_2:该插件生成为一次性操作,后续不能添加骨骼',icon='PLUS')
        row.label(text='                若遗漏想要加效果的骨骼,请点击[一键删除]后,重新操作!')
        row.label(text='')
        row.label(text='Warning_3:骨骼必须在世界坐标中心【默认右上方的按钮已设置回0】',icon='PLUS')


        row.label(text='操作方法:')
        row.label(text='Ops_1:指定场景中存在的骨骼[选中],在鼠标选中进入姿态模式',icon='PLUS')
        row.label(text='                选择想要添加效果的骨骼(多选),点击 [生成控制线]')
        row.label(text='               【生成的集合请勿修改】')
        row.label(text='')
        row.label(text='Ops_2:再点击"一键绑定"和"一键[追踪+软体]',icon='PLUS')

        box=layout.box()
        sp3=box.column()
        sp3.label(text='回弹:【骨骼恢复原本形状的速率:↑越慢↓越快】')
        sp3.label(text='重力:【骨骼受到来自重力的影响:↑越大↓越小】')


        box=layout.row()
        box.label(text='Ops_3:若添加碰撞,选择场景的物体【网格OBJ】点击buttom',icon='PLUS')
        box=layout.box()
        box2=box.column()
        box2.label(text='摩擦:【碰撞体与骨骼互动的影响程度】')
        box2.label(text='距离:【碰撞体与骨骼之间的运算半径】')
        box2.label(text='范围:【碰撞体网格法线和骨骼运算范围】')

#生成选定的骨骼的坐标物体,添加顶点组并判断集合
class Bone_OT_getpostion(bpy.types.Operator):
    bl_idname = 'bone.name'
    bl_label='创建_控制线段'
    bl_options={"REGISTER","UNDO"} #生成左下角popu小窗口
    
    is_panel_on : bpy.props.BoolProperty(name='坐标回原点?',default=True) #设置RNA来控制坐标是否回中心

    #取消poll方法

    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self) #生成弹窗

    def execute(self,context):
        scene=context.scene
        local_zero=scene.is_location
        act_arm=bpy.context.active_object

        arm_obj=scene.arm_obj_point

        if arm_obj != None:
            if act_arm!=arm_obj:
                self.report({'WARNING'},'你当前选中的物体不是指定的骨架物体!')
                return {'FINISHED'}
        else:
            self.report({'WARNING'},'请先选中骨架[插件选定]')
            return {'FINISHED'}
        
        if arm_obj.type == 'ARMATURE': #判断选择的对象是否为骨架
            if arm_obj.mode == 'POSE': #再判断是否进入了姿态模式
                if local_zero == True:  #初始化判断骨架物体 回原点
                    arm_obj.location = (0, 0, 0)
                else:
                    pass
                self.report({'INFO'},'开始计算线段')
                bone_obj=arm_obj
                collection_name = f"SoftBodyDynamics_{bone_obj.name}"

                if collection_name in bpy.data.collections:
                    self.report({'WARNING'},'场景中存在与骨架集合一致的集合,请先删除该集合!')
                    return {'FINISHED'}
                else:
                    collection=bpy.data.collections.new(collection_name)  #新建一个集合
                    bpy.context.scene.collection.children.link(collection)
                    self.coll_bool=True
                    
                find_bone=[bone.name for bone in bone_obj.data.bones if bone.select] #循环获取骨骼选定的对象
                for bone_name in find_bone:
                    bone_postion=bone_obj.pose.bones[bone_name]

                    local_bone_postion_tou=bone_postion.head
                    local_bone_postion_wei=bone_postion.tail

                    global_bone_postion_tou = arm_obj.matrix_world @ local_bone_postion_tou
                    global_bone_postion_wei = arm_obj.matrix_world @ local_bone_postion_wei

                    mesh = bpy.data.meshes.new(bone_name + "_mesh")
                    bm = bmesh.new()

                    # 创建两个顶点，分别对应骨骼的头部和尾部位置
                    v1 = bm.verts.new(global_bone_postion_tou)
                    v2 = bm.verts.new(global_bone_postion_wei)
                    bm.verts.ensure_lookup_table()

                    # 创建连接两个点的边
                    bm.edges.new([v1, v2])
                    bm.edges.ensure_lookup_table()

                    bm.normal_update()

                    # 将 bmesh 数据写入到新建的 mesh
                    bm.to_mesh(mesh)
                    bm.free()

                    # 更新mesh数据
                    mesh.update()
                    mesh.validate()

                    # 创建对象并链接到集合或场景
                    line_obj = bpy.data.objects.new(bone_name, mesh)
                    if self.coll_bool:
                        collection = bpy.data.collections.get(collection_name)
                        if collection:
                            collection.objects.link(line_obj)
                        else:
                            print("集合创建无效")
                            
                    # 为line_obj创建"tou"和"wei"两个顶点组
                    vg_tou = line_obj.vertex_groups.new(name="tou")
                    vg_wei = line_obj.vertex_groups.new(name="wei")
                    # 将第一个顶点(索引0)分配到"tou"组,第二个顶点(索引1)分配到"wei"组
                    vg_tou.add([0], 1.0, 'REPLACE')
                    vg_wei.add([1], 1.0, 'REPLACE')

                #判断是否回到中心
                if self.is_panel_on == True:
                    self.report({'INFO'},'正在让物体坐标回中心')
                    find_coll=bpy.data.collections.get(collection_name)
                    if find_coll:
                        for obj in find_coll.objects:
                            bpy.context.view_layer.objects.active = obj
                            obj.select_set(True)
                            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')
                            #obj.select_set(False)
                    else:
                        self.report({'ERROR'},'没有寻找到存放物体的集合')
                        return {'FINISHED'}  

                    
                self.report({'INFO'},'回中心完成!')
            #隐藏排除集合
                view_layer=bpy.context.view_layer
                get_view_coll=bpy.data.collections[collection_name]

                for view_col in bpy.data.collections:
                    if view_col==get_view_coll:
                        #view_layer.layer_collection.children[view_col.name].exclude = True
                        self.report({'INFO'},'[存在集合]创建完成！')
                    else:
                        pass
                return {'FINISHED'}      
            else:
                self.report({'WARNING'},'请进入姿态模式')
                return {'FINISHED'}
        else:
            self.report({'ERROR'},'ERROR')
            return {'FINISHED'}

#一键删除掉插件的线段物体和选定的集合
class DELET_OT_OBJCOLL(bpy.types.Operator):
    bl_idname='del.obj'
    bl_label='一键删除线段物体or集合'
    bl_options={"REGISTER","UNDO"}

    is_coll_Get : bpy.props.BoolProperty(name='删除创建的集合(默认)',default=True)#判断是否连带删除集合 默认True

#获取集合对象
    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        scene=context.scene
        arm_obj=scene.arm_obj_point


        if arm_obj is not None:
            pass
        else:
            self.report({'ERROR'},'请先选中骨架[插件选定]')
            return {'FINISHED'}

        if arm_obj.type == 'ARMATURE': #判断是否选中的为骨架
            coll_get=bpy.data.collections.get(f"SoftBodyDynamics_{arm_obj.name}")

            if coll_get is not None:  #判断是否有集合对象
                for obj in coll_get.objects: #循环删除集合里的对象
                    bpy.data.objects.remove(obj)
            else:
                self.report({'ERROR'},'找不到集合对象,请创建线段的时候选择【创建集合】')
                return {'FINISHED'}
            
            if self.is_coll_Get:
                bpy.data.collections.remove(coll_get) #判断并是否一起删除掉集合
                return {'FINISHED'}
            else:
                return {'FINISHED'}
        else:
            self.report({'ERROR'},'请先选中骨架')
            return {'FINISHED'}
            
#一键自动绑定
class Skin_OT_Bone(bpy.types.Operator):
    bl_idname='skin.obj'
    bl_label='蒙皮绑定骨架'
    bl_options={"REGISTER","UNDO"}

    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self,context):
        #检查场景是否存在骨架和骨架名称一致的集合
        self.report({'INFO'},'正在蒙皮Skin')
        scene=context.scene
        arm_obj=scene.arm_obj_point
        
        if arm_obj is not None:
            arm_name=arm_obj.name
            if arm_obj.type == 'ARMATURE':
                coll_name=f"SoftBodyDynamics_{arm_name}"   #如果存在获取其名字
                #加限制防止出大BUG
                if coll_name in bpy.data.collections:
                    coll=bpy.data.collections[coll_name]
                    if len(coll.objects)> 0 :
                        for obj in coll.objects:
                            if obj.parent is not None: #因为绑定后父级就是骨架,不存在就代表没绑定
                                self.report({'ERROR'},'已进行过操作,请勿重试!')
                                return {'FINISHED'}
                    else:
                        self.report({'ERROR'},'集合是空的!删除后重新创建')
                        return {'FINISHED'}
                else:
                    self.report({'ERROR'},'不存在集合,请先创建线段')
                    return {'FINISHED'} 
           
                get_Bone_data=bpy.data.objects[arm_name] #获取骨架信息
                collection=bpy.data.collections.get(coll_name) #获取命名一致的集合属性

                for obj in collection.objects:
                    select_name=obj.name
                    select_bone=get_Bone_data.data.bones.get(select_name)#获取当前选定骨骼的属性
                    if select_bone:   
                        parent_bool=select_bone.parent
                        if parent_bool!=None:
                            parent_name=parent_bool.name
                        else:
                            self.report({'WARNING'},'选取的骨骼不规范[控制骨为None]请重新生成!')
                            return {'FINISHED'}

                        #print('当前物体'+select_name)
                        #print('父骨骼'+parent_name)
                        arm=get_Bone_data.data

                        if parent_name in get_Bone_data.data.bones:
                            skin_bone=arm.bones[parent_name] #获取绑定的骨骼
                            #绑定的核心逻辑
                            seletd_1=bpy.data.objects[select_name] #获取第一个初始对象OBJ
                            seletd_1.select_set(True)  #选中状态

                            bone_2=bpy.data.objects[arm_name] #获取到骨架对象
                            bone_2.select_set(True)  #选中状态

                            bpy.context.view_layer.objects.active = get_Bone_data #将活动对象先设置为骨架
                            bpy.ops.object.mode_set(mode='POSE') 
                             
                            bpy.ops.pose.select_all(action='DESELECT') #清除掉所有的选择
                            arm.bones.active=skin_bone #再将活动对象状态选择为父骨骼
                            skin_bone.select=True

                            active_object = bpy.context.view_layer.objects.active
                            active_bone_name = active_object.data.bones.active.name
                            #print('当前活动对象为:'+active_bone_name)
                             
                           
                            bpy.ops.object.parent_set(type='BONE')
                            bpy.ops.object.mode_set(mode='OBJECT')

                            #取消全选所有物体(很重要)
                            scene = bpy.context.scene
                            for obj in scene.objects:
                                obj.select_set(False)

                    else:
                        pass
                self.report({'INFO'},'自动绑定完成!')
                return {'FINISHED'}
            else:
                pass
        self.report({'WARNING'},'Skin没有执行,可能场景中不存在线段集合!')
        return {'FINISHED'}

#设置阻尼追踪和软体 
class Setting_OT_Bone(bpy.types.Operator):
    bl_idname='setting.bone'
    bl_label='设置阻尼追踪效果器'
 

    RNA_Moca : bpy.props.FloatProperty(name='初始摩擦:',default=15.0)
    RNA_Zhil : bpy.props.FloatProperty(name='初始质量:',default=0.2)


    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):   #获取集合内容和骨骼属性,添加效果器
        scene=context.scene
        arm_obj=scene.arm_obj_point
        
        if arm_obj is not None:

            arm_name=arm_obj.name
            coll_name=f"SoftBodyDynamics_{arm_name}"
            if coll_name in bpy.data.collections:
                coll=bpy.data.collections[coll_name]
                if len(coll.objects)> 0 :
                    pass
                else:
                    self.report({'WARNING'},'集合是空的!请正确操作')
                    return {'FINISHED'}
                   
                bone=bpy.data.objects[arm_name]   
                coll=bpy.data.collections[coll_name]
        
                for c in coll.objects:   #获取集合内的每个物体
                    bpy.context.view_layer.objects.active = bone 
                    bpy.ops.object.mode_set(mode='POSE')
                    bpy.ops.pose.select_all(action='DESELECT')

                    group_name='wei'

                    #添加阻尼约束
                    pose_bone=bpy.data.objects[arm_name].pose.bones.get(c.name) #获取骨架内姿态模式下的骨骼
                    cont_name='addons_阻尼'

                    if pose_bone:
                        cont=pose_bone.constraints.new(type='DAMPED_TRACK')
                        cont.name=cont_name

                        target_obj=bpy.data.objects.get(c.name)
                        cont.target=target_obj

                        obj_vargroup=target_obj.vertex_groups
                        for group in obj_vargroup:
                            if group_name == group.name:
                                cont.subtarget=group_name
                        
                for obj in coll.objects: #循环获取指定集合的每个物体    
                    bpy.context.view_layer.objects.active=obj
                    obj.select_set(True)
                    
                    obj.modifiers.new(name='Softbody',type='SOFT_BODY')

                    bpy.context.object.modifiers["Softbody"].settings.friction = 15
                    bpy.context.object.modifiers["Softbody"].settings.mass = 0.2
                    bpy.context.object.modifiers["Softbody"].settings.vertex_group_mass = "tou"

                bpy.ops.object.select_all(action='DESELECT')
                self.report({'INFO'},'顶点组 or 设置完成!')
                return{'FINISHED'}
            else:
                self.report({'WARNING'},'列表中不存在骨架对应的集合')        
                return {'FINISHED'}
        else:
            self.report({'WARNING'},'请先选中骨架[插件选择]')        
            return {'FINISHED'}
        
class Setting_OT_Modifiers(bpy.types.Operator):
    bl_idname='setting.mod'
    bl_label='修改软体设置'
    
    #def invoke(self,context,event):
        #return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        scene=context.scene
        moni=scene.R_moni
        zhi=scene.R_zhi
        is_bone_rege=scene.is_bone_Re

        arm_obj=scene.arm_obj_point
        
        if arm_obj is not None:
            arm_name=arm_obj.name
            if arm_obj.type=='ARMATURE':
                obj_name=f"SoftBodyDynamics_{arm_name}"

                if obj_name in bpy.data.collections:
                    coll=bpy.data.collections[obj_name]
                    if len(coll.objects)> 0 :
                        pass
                    else:
                        self.report({'WARNING'},'集合是空的!请正确操作')
                        return {'FINISHED'}
                else:
                    self.report({'WARNING'},'不存在集合')
                    return {'FINISHED'}
                
                for obj_c in coll.objects: 
                    modifiers=obj_c.modifiers
                    for mod in modifiers:
                        if mod.type == 'SOFT_BODY':
                            self.report({'INFO'},obj_c.name+'存在软体!')
                            coll_enum=bpy.data.collections[obj_name]
                            for obj in coll_enum.objects: #循环获取指定集合的每个物体    
                                bpy.context.view_layer.objects.active=obj
                                obj.select_set(True)

                                #参数修改
                                if is_bone_rege: #是否为重置
                                    scene.R_moni=18.0
                                    scene.R_zhi=0.15
                                    bpy.context.object.modifiers["Softbody"].settings.friction = 18
                                    bpy.context.object.modifiers["Softbody"].settings.mass = 0.15
                                    self.report({'INFO'},obj.name+'重置完成!')
                                    bpy.ops.object.select_all(action='DESELECT') 
                                    scene.is_bone_Re=False
                                else:
                                    bpy.context.object.modifiers["Softbody"].settings.friction =moni
                                    bpy.context.object.modifiers["Softbody"].settings.mass = zhi
                                    self.report({'INFO'},obj.name+'设置完成!')
                                    bpy.ops.object.select_all(action='DESELECT')  
                            self.report({'INFO'},'创建&修改完成')
                            return {'FINISHED'}
                        else:
                            self.report({'WARNING'},'列表中的'+obj_c.name+'没有找到"软体"的属性')
                            pass
                    self.report({'WARNING'},'没有找到任何物理属性!')
                    return {'FINISHED'}
                    
                self.report({'WARNING'},'没找到物体!')
                return {'FINISHED'}
            else:
                pass
        self.report({'WARNING'},'没找到对象')
        return {'FINISHED'}

#设置碰撞体
class Setting_OT_Objects(bpy.types.Operator):
    bl_idname='setting.objects'
    bl_label='设置碰撞体[obj]'
    

    is_RNAbool : bpy.props.BoolProperty(name='移除x / 创建√',default=True)

    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        scene=context.scene
    
        obj=bpy.context.selected_objects #_list

        for ob in obj:
            obj_name=ob.name
            if bpy.data.objects[obj_name].type != 'MESH': #首先排除掉网格物体的其余物体
                pass
            else:
                modif_obj=bpy.data.objects[obj_name].modifiers  
                if modif_obj: #判断物体是否设置了效果器
                    for mod_obj in modif_obj:  
                        if mod_obj.type == 'COLLISION': #存在碰撞体的物体
                            if self.is_RNAbool == True: 
                                self.report({'WARNING'},'已存在,请勿重复创建!')
                                return {'FINISHED'}
                            else:
                                modif_obj.remove(mod_obj)
                                self.report({'INFO'},obj_name+'碰撞已经移除!')
                                pass
                        else:
                            self.report({'WARNING'},'不存在物理!')
                            return {'FINISHED'}
                    return {'FINISHED'}    
                else:
                    if self.is_RNAbool==True:
                        for act_obj_name in obj:
                            bpy.context.view_layer.objects.active=bpy.data.objects[act_obj_name.name]

                            bpy.ops.object.modifier_add(type='COLLISION')
                            bpy.context.object.collision.thickness_inner = 1
                            self.report({'INFO'},'设置碰撞体完成！')
                        return {'FINISHED'}
        self.report({'WARNING'},'没有任何选中或找到的对象')
        return {'FINISHED'}
                    
class Seting_OT_collntion(bpy.types.Operator):
    bl_idname='setting.colln'
    bl_label='碰撞体参数重置'

    #def invoke(self,context,event):
        #return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        scene=context.scene
        Bool_Obj=True
        pos=scene.R_pos
        zuni=scene.R_Zuni
        juli=scene.R_Juli
        is_rege=scene.is_obj_Re

        moifier_ty_name='COLLISION'
        for obj in bpy.context.scene.objects:
            modifiers=obj.modifiers

            for mod in modifiers:
                if mod.type == moifier_ty_name:
                    Bool_Obj=False
                    bpy.ops.object.select_all(action='DESELECT')
                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)
                    if is_rege==False: #判断是否为重置
                        bpy.context.object.collision.damping = zuni
                        bpy.context.object.collision.thickness_inner =pos
                        bpy.context.object.collision.thickness_outer =juli
                    else:
                        scene.R_Zuni=0.1
                        scene.R_pos=0.9
                        scene.R_Juli=0.12
                        bpy.context.object.collision.damping = 0.1
                        bpy.context.object.collision.thickness_inner =0.9
                        bpy.context.object.collision.thickness_outer =0.12
                        scene.is_obj_Re=False
        if Bool_Obj:
            self.report({'WARNING'},'不存在任何碰撞物体!')
            return {'FINISHED'}
        self.report({'INFO'},'"碰撞"修改&创建完成完成！')
        return {'FINISHED'}

class Bake_OT_Setting(bpy.types.Operator):
    bl_idname='setting.bake'
    bl_label='烘焙关键帧'
 
    def invoke(self,context,event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        scene=context.scene
        star=scene.star_bake
        stop=scene.stop_bake
        bake_del=scene.is_bake

        for obj in bpy.data.objects:
            if obj.type=='ARMATURE':
                obj_name=f"SoftBodyDynamics_{obj.name}"

                if obj_name in bpy.data.collections:
                    coll=bpy.data.collections[obj_name]
                    if len(coll.objects)> 0 :
                        pass
                    else:
                        self.report({'WARNING'},'集合是空的!请正确操作')
                        return {'FINISHED'}
                else:
                    self.report({'WARNING'},'不存在集合')
                    return {'FINISHED'}
                
                self.report({'INFO'},'集合物体:'+obj_name)
                for obj_c in coll.objects: 
                    bpy.ops.object.select_all(action='DESELECT')
                    bake_obj=bpy.data.objects[obj_c.name]
                    bpy.context.view_layer.objects.active=bake_obj

                    bpy.context.object.modifiers["Softbody"].point_cache.frame_start = star
                    bpy.context.object.modifiers["Softbody"].point_cache.frame_end = stop

                    bake_obj.select_set(True)
                    if bake_del:
                        bpy.ops.ptcache.free_bake_all() #删除所有烘焙
                        self.report({'INFO'},'删除所有烘焙的结果')
                        return {'FINISHED'}
                    else:
                        pass
                    bpy.ops.ptcache.bake_all(bake=True)
                    bake_obj.select_set(False)
                self.report({'INFO'},'烘焙完成')
                return {'FINISHED'}
        self.report({'WARNING'},'没有找到任何对象')
        return {'FINISHED'}
        