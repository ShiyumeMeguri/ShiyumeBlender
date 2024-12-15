import typing
import bpy
#from bpy.types import Context
from . import softbody as Softbody

bl_info = {
    "name" : "Physics_Dy_Bone",
    "author" : "覆Fu【B站_id:51193944】",
    "description" : "一个简单自用的骨骼插件[优化版] 原理:bvBV1Wg411x74p",
    "blender" : (3, 3, 1),
    "version" : (0, 2, 1),
    "location" : "Properties > Scene > VIEW_3D",
    "warning" : "没有经过长久的测试,可能存在意想不到or闪退的BUG",
    "category" : "Generic"
}

classs=[

    Softbody.Bone_OT_getpostion,
    Softbody.DELET_OT_OBJCOLL,
    Softbody.Skin_OT_Bone,
    Softbody.Setting_OT_Bone,
    Softbody.Setting_OT_Modifiers,
    Softbody.Setting_OT_Objects,
    Softbody.Seting_OT_collntion,
    Softbody.Bake_OT_Setting,
    
    Softbody.UI_PT_Bone,
    Softbody.UI_PT_Explain,
    #Softbody.UI_PT_Father_panel
]

def register():
    Softbody.softbody_RNA()
    for cls in classs:
        bpy.utils.register_class(cls)
    
def unregister():
    Softbody.remove_softbody_RNA()

    for cls in classs:
        bpy.utils.unregister_class(cls)
    
if __name__ == "__main__":
    register()